from __future__ import absolute_import

from jsonschema import validate as json_schema_validate

SCHEMA = {
    'type': 'object',

    'definitions': {
        'uri': {
            'type': 'string',
            'format': 'uri',
        },
        'options': {
            'type': 'array',
            'items': {
                'type': 'array',
                'minItems': 2,
                'maxItems': 2,
                'items': [
                    {'type': 'string'},
                    {'anyOf': [
                        {'type': 'string'},
                        {'type': 'number'},
                    ]}
                ]
            }
        },
        'select': {
            'type': 'object',
            'properties': {
                'label': {
                    'type': 'string',
                    'errors': {
                        'type': 'Label must be a string',
                    },
                },
                'name': {
                    'type': 'string',
                },
                'uri': {
                    '$ref': '#/definitions/uri',
                },
                'options': {
                    '$ref': '#/definitions/options',
                },
            },
            'required': ['name'],
            'oneOf': [
                {'required': ['uri']},
                {'required': ['options']},
            ],
        },

        'text': {

        },

        'header': {

        },

        'image': {

        },

        'video': {

        },

        'markdown': {

        },

        'issue-link': {

        },

        'alert-rule-action': {

        },

        'issue-media': {

        },
    },

    'properties': {
        'select': {
            '$ref': '#/definitions/select',
        },
    },
}


def validate(value, type):
    json_schema_validate(
        instance={type: value},
        schema=SCHEMA,
    )
