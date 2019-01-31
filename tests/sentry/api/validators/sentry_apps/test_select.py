from __future__ import absolute_import

from jsonschema import ValidationError

from sentry.testutils import TestCase
from sentry.api.validators.sentry_apps.schema import validate


class TestSelectSchemaValidation(TestCase):
    def test_valid_schema_with_options(self):
        schema = {
            'name': 'title',
            'label': 'Title',
            'options': [
                ['Stuff', 'stuff'],
                ['Things', 'things'],
            ]
        }

        # Doesn't raise
        validate(schema, 'select')

    def test_valid_schema_options_with_numeric_value(self):
        schema = {
            'name': 'title',
            'label': 'Title',
            'options': [
                ['Stuff', 1],
                ['Things', 2],
            ]
        }

        validate(schema, 'select')

    def test_valid_schema_with_uri(self):
        schema = {
            'name': 'title',
            'label': 'Title',
            'uri': '/foo',
        }

        validate(schema, 'select')

    def test_invalid_schema_missing_uri_and_options(self):
        schema = {
            'name': 'title',
            'label': 'Title',
        }

        with self.assertRaises(ValidationError):
            validate(schema, 'select')

    def test_invalid_schema_missing_name(self):
        schema = {
            'label': 'Title',
            'uri': '/foo',
        }

        with self.assertRaises(ValidationError):
            validate(schema, 'select')
