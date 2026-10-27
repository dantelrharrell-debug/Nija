"""Offline tests: no requests to live IONOS, PocketBase, Kraken, or Stripe."""
from __future__ import annotations

import io
import json
from unittest import TestCase
from urllib import error

from scripts.nija_pocketbase_vault_rule_inspection_v481 import (
    AuditDenied, _unique_index, inspect_collection, inspect_live,
)


def fixture():
    owner = '@request.auth.id != "" && @request.auth.verified = true && user_id = @request.auth.id'
    create = '@request.auth.id != "" && @request.auth.verified = true && @request.body.user_id = @request.auth.id'
    vault = {
        "name": "nija_broker_vault", "type": "base",
        "listRule": owner, "viewRule": owner, "createRule": create,
        "updateRule": None, "deleteRule": None,
        "indexes": ['CREATE UNIQUE INDEX idx_nija_vault_scope ON "nija_broker_vault" ("user_id", "broker", "environment")'],
        "fields": [
            {"name": "user_id", "type": "relation", "required": True,
             "options": {"collectionId": "user_coll_1", "maxSelect": 1}},
            {"name": "broker", "type": "select"},
            {"name": "environment", "type": "select"},
            {"name": "ciphertext", "type": "text"},
        ],
    }
    users = {"name": "users", "type": "auth", "id": "user_coll_1"}
    return vault, users


class FakeResponse:
    status = 200
    def __init__(self, payload):
        self.payload = json.dumps(payload).encode()
    def __enter__(self):
        return self
    def __exit__(self, *_):
        pass
    def read(self, size):
        return self.payload[:size]


class FakeOpener:
    def __init__(self, vault, users, failure=None):
        self.vault, self.users = vault, users
        self.calls = []
        self.failure = failure
    def open(self, req, timeout):
        self.calls.append(req)
        if self.failure:
            raise self.failure
        if req.full_url.endswith('/users'):
            return FakeResponse(self.users)
        return FakeResponse(self.vault)


class Tests(TestCase):
    def test_structural_fixture_is_not_member_certification(self):
        vault, users = fixture()
        result = inspect_collection(vault, users)
        self.assertEqual(result['status'], 'STRUCTURE_MATCH')
        self.assertTrue(result['structural_rule_checks_passed'])
        self.assertFalse(result['member_vault_certified'])
        self.assertFalse(result['cross_member_negative_tests_passed'])
        self.assertFalse(result['intake_authorized'])

    def test_new_pocketbase_relation_field_format_is_accepted(self):
        vault, users = fixture()
        vault['fields'][0].pop('options')
        vault['fields'][0]['collectionId'] = 'user_coll_1'
        vault['fields'][0]['maxSelect'] = 0
        self.assertTrue(inspect_collection(vault, users)['structural_rule_checks_passed'])

    def test_no_token_or_external_origin_does_not_make_request(self):
        vault, users = fixture()
        opener = FakeOpener(vault, users)
        for origin, token in [('https://nijaaitrading.com', ''),
                              ('https://evil.example', 'redacted-token'),
                              ('http://nijaaitrading.com', 'redacted-token'),
                              ('https://nijaaitrading.com/a', 'redacted-token')]:
            with self.subTest(origin=origin, token=bool(token)):
                with self.assertRaises(AuditDenied):
                    inspect_live(origin, token, opener=opener)
        self.assertFalse(opener.calls)

    def test_only_two_exact_authenticated_collection_reads(self):
        vault, users = fixture()
        opener = FakeOpener(vault, users)
        result = inspect_live('https://nijaaitrading.com', 'redacted-token', opener=opener)
        self.assertTrue(result['structural_rule_checks_passed'])
        self.assertEqual(len(opener.calls), 2)
        for req in opener.calls:
            self.assertEqual(req.get_method(), 'GET')
            self.assertEqual(req.get_header('Authorization'), 'Bearer redacted-token')
            self.assertTrue(req.full_url.startswith('https://nijaaitrading.com/.sfs-be/api/collections/'))

    def test_cross_owner_create_or_owner_read_rules_rejected(self):
        for rule in ['createRule', 'viewRule', 'listRule']:
            vault, users = fixture()
            vault[rule] = '@request.auth.verified = true'
            self.assertIn('rule_' + rule, inspect_collection(vault, users)['missing_or_unverified'])

    def test_whitespace_inside_auth_string_must_not_be_normalized(self):
        vault, users = fixture()
        vault['viewRule'] = vault['viewRule'].replace('id != ""', 'id != " "')
        self.assertIn('rule_viewRule', inspect_collection(vault, users)['missing_or_unverified'])

    def test_reassignment_update_rule_rejected(self):
        vault, users = fixture()
        vault['updateRule'] = vault['viewRule']
        self.assertIn('rule_updateRule', inspect_collection(vault, users)['missing_or_unverified'])

    def test_unverified_unique_index_rejected(self):
        vault, users = fixture()
        for ddl in ['CREATE INDEX idx_test ON nija_broker_vault (user_id, broker, environment)',
                    'CREATE UNIQUE INDEX idx_test ON nija_broker_vault (user_id, broker, environment) WHERE active=1',
                    'CREATE UNIQUE INDEX idx_test ON nija_broker_vault (user_id, broker)']:
            vault['indexes'] = [ddl]
            self.assertIn('scope_unique_index', inspect_collection(vault, users)['missing_or_unverified'])
        self.assertFalse(_unique_index('not a list'))

    def test_relation_must_be_single_required_and_linked_to_users(self):
        for variant in ({'type': 'text'}, {'required': False},
                        {'options': {'collectionId': 'other', 'maxSelect': 1}},
                        {'options': {'collectionId': 'user_coll_1', 'maxSelect': 2}}):
            vault, users = fixture()
            vault['fields'][0].update(variant)
            self.assertIn('verified_owner_relation', inspect_collection(vault, users)['missing_or_unverified'])

    def test_unauthorized_or_gateway_failures_are_redacted(self):
        vault, users = fixture()
        for status in (302, 401, 403, 500, 504):
            opener = FakeOpener(vault, users, error.HTTPError('https://example', status, 'secret response', {}, io.BytesIO(b'secret')))
            with self.subTest(status=status), self.assertRaises(AuditDenied) as cm:
                inspect_live('https://nijaaitrading.com', 'redacted-token', opener=opener)
            self.assertEqual(str(cm.exception), 'collection_api_unavailable')
            self.assertNotIn('secret', str(cm.exception))
