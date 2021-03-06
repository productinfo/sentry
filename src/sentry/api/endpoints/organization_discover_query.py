from __future__ import absolute_import

import re
import six
from functools32 import partial
from copy import deepcopy

from rest_framework import serializers
from rest_framework.response import Response
from rest_framework.exceptions import PermissionDenied

from sentry.api.serializers.rest_framework import ListField
from sentry.api.bases.organization import OrganizationPermission
from sentry.api.bases import OrganizationEndpoint
from sentry.api.paginator import GenericOffsetPaginator
from sentry.api.utils import get_date_range_from_params, InvalidParams
from sentry.models import Project, ProjectStatus, OrganizationMember, OrganizationMemberTeam
from sentry.utils import snuba
from sentry import roles
from sentry import features
from sentry.auth.superuser import is_active_superuser


class OrganizationDiscoverQueryPermission(OrganizationPermission):
    scope_map = {
        'POST': ['org:read', 'project:read'],
    }


class DiscoverQuerySerializer(serializers.Serializer):
    projects = ListField(
        child=serializers.IntegerField(),
        required=True,
        allow_null=False,
    )
    start = serializers.CharField(required=False, allow_none=True)
    end = serializers.CharField(required=False, allow_none=True)
    range = serializers.CharField(required=False, allow_none=True)
    statsPeriod = serializers.CharField(required=False, allow_none=True)
    statsPeriodStart = serializers.CharField(required=False, allow_none=True)
    statsPeriodEnd = serializers.CharField(required=False, allow_none=True)
    fields = ListField(
        child=serializers.CharField(),
        required=False,
        allow_null=True,
    )
    limit = serializers.IntegerField(min_value=0, max_value=10000, required=False)
    rollup = serializers.IntegerField(required=False)
    orderby = serializers.CharField(required=False)
    conditions = ListField(
        child=ListField(),
        required=False,
        allow_null=True,
    )
    aggregations = ListField(
        child=ListField(),
        required=False,
        allow_null=True,
        default=[]
    )
    groupby = ListField(
        child=serializers.CharField(),
        required=False,
        allow_null=True,
    )
    turbo = serializers.BooleanField(required=False)

    def __init__(self, *args, **kwargs):
        super(DiscoverQuerySerializer, self).__init__(*args, **kwargs)

        data = kwargs['data']

        fields = data.get('fields') or []

        match = next(
            (
                self.get_array_field(field).group(1)
                for field
                in fields
                if self.get_array_field(field) is not None
            ),
            None
        )
        self.arrayjoin = match if match else None

    def validate(self, data):
        data['arrayjoin'] = self.arrayjoin

        # prevent conflicting date ranges from being supplied
        date_fields = ['start', 'statsPeriod', 'range', 'statsPeriodStart']
        date_fields_provided = len([data.get(f) for f in date_fields if data.get(f) is not None])
        if date_fields_provided == 0:
            raise serializers.ValidationError('You must specify a date filter')
        elif date_fields_provided > 1:
            raise serializers.ValidationError('Conflicting date filters supplied')

        try:
            start, end = get_date_range_from_params({
                'start': data.get('start'),
                'end': data.get('end'),
                'statsPeriod': data.get('statsPeriod') or data.get('range'),
                'statsPeriodStart': data.get('statsPeriodStart'),
                'statsPeriodEnd': data.get('statsPeriodEnd'),
            }, optional=True, validate_window=False)
        except InvalidParams as exc:
            raise serializers.ValidationError(exc.message)

        if start is None or end is None:
            raise serializers.ValidationError('Either start and end dates or range is required')

        data['start'] = start
        data['end'] = end

        return data

    def validate_projects(self, attrs, source):
        projects = attrs[source]
        org_projects = set(project[0] for project in self.context['projects'])

        if not set(projects).issubset(org_projects):
            raise PermissionDenied

        return attrs

    def validate_conditions(self, attrs, source):
        # Handle error (exception_stacks), stack(exception_frames)
        if attrs.get(source):
            conditions = [self.get_condition(condition) for condition in attrs[source]]
            attrs[source] = conditions
        return attrs

    def validate_aggregations(self, attrs, source):
        valid_functions = set(['count()', 'uniq', 'avg'])
        requested_functions = set(agg[0] for agg in attrs[source])

        if not requested_functions.issubset(valid_functions):
            invalid_functions = ', '.join((requested_functions - valid_functions))

            raise serializers.ValidationError(
                u'Invalid aggregate function - {}'.format(invalid_functions)
            )

        return attrs

    def get_array_field(self, field):
        pattern = r"^(error|stack)\..+"
        return re.search(pattern, field)

    def get_condition(self, condition):
        array_field = self.get_array_field(condition[0])
        has_equality_operator = condition[1] in ('=', '!=')

        # Cast boolean values to 1 / 0
        if isinstance(condition[2], bool):
            condition[2] = int(condition[2])

        # Apply has function to any array field if it's = / != and not part of arrayjoin
        if array_field and has_equality_operator and (array_field.group(1) != self.arrayjoin):
            value = condition[2]

            if (isinstance(value, six.string_types)):
                value = u"'{}'".format(value)

            bool_value = 1 if condition[1] == '=' else 0

            return [['has', [array_field.group(0), value]], '=', bool_value]

        return condition


class OrganizationDiscoverQueryEndpoint(OrganizationEndpoint):
    permission_classes = (OrganizationDiscoverQueryPermission, )

    def get_json_type(self, snuba_type):
        """
        Convert Snuba/Clickhouse type to JSON type
        Default is string
        """

        # Ignore Nullable part
        nullable_match = re.search(r'^Nullable\((.+)\)$', snuba_type)

        if nullable_match:
            snuba_type = nullable_match.group(1)
        # Check for array

        array_match = re.search(r'^Array\(.+\)$', snuba_type)
        if array_match:
            return 'array'

        types = {
            'UInt8': 'boolean',
            'UInt16': 'integer',
            'UInt32': 'integer',
            'UInt64': 'integer',
            'Float32': 'number',
            'Float64': 'number',
        }

        return types.get(snuba_type, 'string')

    def handle_results(self, snuba_results, requested_query, projects):
        if 'project.name' in requested_query['selected_columns']:
            project_name_index = requested_query['selected_columns'].index('project.name')
            snuba_results['meta'].insert(
                project_name_index, {
                    'name': 'project.name', 'type': 'String'})
            if 'project.id' not in requested_query['selected_columns']:
                snuba_results['meta'] = [
                    field for field in snuba_results['meta'] if field['name'] != 'project.id'
                ]

            for result in snuba_results['data']:
                if 'project.id' in result:
                    result['project.name'] = projects[result['project.id']]
                    if 'project.id' not in requested_query['selected_columns']:
                        del result['project.id']

        if 'project.name' in requested_query['groupby']:
            project_name_index = requested_query['groupby'].index('project.name')
            snuba_results['meta'].insert(
                project_name_index, {
                    'name': 'project.name', 'type': 'String'})
            if 'project.id' not in requested_query['groupby']:
                snuba_results['meta'] = [
                    field for field in snuba_results['meta'] if field['name'] != 'project.id'
                ]

            for result in snuba_results['data']:
                if 'project.id' in result:
                    result['project.name'] = projects[result['project.id']]
                    if 'project.id' not in requested_query['groupby']:
                        del result['project.id']

        # Convert snuba types to json types
        for col in snuba_results['meta']:
            col['type'] = self.get_json_type(col.get('type'))

        return snuba_results

    def do_query(self, projects, request, **kwargs):
        requested_query = deepcopy(kwargs)

        selected_columns = kwargs['selected_columns']
        groupby_columns = kwargs['groupby']

        if 'project.name' in requested_query['selected_columns']:
            selected_columns.remove('project.name')
            if 'project.id' not in selected_columns:
                selected_columns.append('project.id')

        if 'project.name' in requested_query['groupby']:
            groupby_columns.remove('project.name')
            if 'project.id' not in groupby_columns:
                groupby_columns.append('project.id')

        for aggregation in kwargs['aggregations']:
            if aggregation[1] == 'project.name':
                aggregation[1] = 'project.id'

        if not kwargs['aggregations']:

            data_fn = partial(
                snuba.transform_aliases_and_query,
                referrer='discover',
                **kwargs
            )
            return self.paginate(
                request=request,
                on_results=lambda results: self.handle_results(results, requested_query, projects),
                paginator=GenericOffsetPaginator(data_fn=data_fn),
                max_per_page=1000
            )
        else:
            snuba_results = snuba.transform_aliases_and_query(
                referrer='discover',
                **kwargs
            )
            return Response(self.handle_results(
                snuba_results,
                requested_query,
                projects,
            ), status=200)

    def has_projects_access(self, user, organization, requested_projects):
        member = OrganizationMember.objects.get(
            user=user, organization=organization)

        has_global_access = roles.get(member.role).is_global

        if has_global_access:
            return True

        member_project_list = Project.objects.filter(
            organization=organization,
            teams__in=OrganizationMemberTeam.objects.filter(
                organizationmember=member,
            ).values('team'),
        ).values_list('id', flat=True)

        return set(requested_projects).issubset(set(member_project_list))

    def post(self, request, organization):

        if not features.has('organizations:discover', organization, actor=request.user):
            return Response(status=404)

        requested_projects = request.DATA['projects']

        if not is_active_superuser(request) and not self.has_projects_access(
            request.user, organization, requested_projects
        ):
            return Response("Invalid projects", status=400)

        projects = Project.objects.filter(
            organization=organization,
            status=ProjectStatus.VISIBLE,
        ).values_list('id', 'slug')

        serializer = DiscoverQuerySerializer(data=request.DATA, context={'projects': projects})

        if not serializer.is_valid():
            return Response(serializer.errors, status=400)

        serialized = serializer.object

        has_aggregations = len(serialized.get('aggregations')) > 0

        selected_columns = [] if has_aggregations else serialized.get('fields')

        projects_map = {}
        for project in projects:
            projects_map[project[0]] = project[1]

        # Make sure that all selected fields are in the group by clause if there
        # are aggregations
        groupby = serialized.get('groupby') or []
        fields = serialized.get('fields') or []
        if has_aggregations:
            for field in fields:
                if field not in groupby:
                    groupby.append(field)

        return self.do_query(
            projects=projects_map,
            start=serialized.get('start'),
            end=serialized.get('end'),
            groupby=groupby,
            selected_columns=selected_columns,
            conditions=serialized.get('conditions'),
            orderby=serialized.get('orderby'),
            limit=serialized.get('limit'),
            aggregations=serialized.get('aggregations'),
            rollup=serialized.get('rollup'),
            filter_keys={'project.id': serialized.get('projects')},
            arrayjoin=serialized.get('arrayjoin'),
            request=request,
            turbo=serialized.get('turbo'),
        )
