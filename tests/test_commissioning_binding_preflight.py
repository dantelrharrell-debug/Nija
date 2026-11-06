"""Offline regression coverage for the inert commissioning binding inventory."""
import unittest

from bot.commissioning_binding_preflight import (
    REQUIRED_BINDINGS, inspect_commissioning_bindings,
)
from bot.pretrade_attestation_validation_v452 import REQUIRED


class BindingPreflightTests(unittest.TestCase):
    def test_missing_registry_never_authorizes(self):
        result = inspect_commissioning_bindings(None)
        self.assertEqual(set(result["missing_bindings"]), set(REQUIRED_BINDINGS))
        self.assertEqual(set(result["missing_provider_id_fields"]), set(REQUIRED))
        self.assertFalse(result["activation_allowed"])
        self.assertFalse(result["collector_installed"])

    def test_supplied_bindings_are_not_certification(self):
        bindings = {name: object() for name in REQUIRED_BINDINGS}
        bindings["reviewed_provider_ids"] = {field: "id-" + field for field in REQUIRED}
        result = inspect_commissioning_bindings(bindings)
        self.assertTrue(result["complete_binding_inventory"])
        self.assertFalse(result["authenticated_evidence_verified"])
        self.assertFalse(result["authorizes_orders"])
        self.assertFalse(result["activation_allowed"])

    def test_partial_provider_ids_are_reported(self):
        bindings = {name: object() for name in REQUIRED_BINDINGS}
        bindings["reviewed_provider_ids"] = {REQUIRED[0]: "id"}
        result = inspect_commissioning_bindings(bindings)
        self.assertEqual(set(result["missing_provider_id_fields"]), set(REQUIRED[1:]))
        self.assertFalse(result["complete_binding_inventory"])

    def test_duplicate_provider_identity_denied(self):
        bindings = {name: object() for name in REQUIRED_BINDINGS}
        bindings["reviewed_provider_ids"] = {field: "shared" for field in REQUIRED}
        result = inspect_commissioning_bindings(bindings)
        self.assertFalse(result["unique_provider_ids"])
        self.assertFalse(result["complete_binding_inventory"])
        self.assertFalse(result["activation_allowed"])

    def test_unexpected_provider_field_denied(self):
        bindings = {name: object() for name in REQUIRED_BINDINGS}
        bindings["reviewed_provider_ids"] = {
            **{field: "id-" + field for field in REQUIRED}, "unreviewed": "id-extra",
        }
        result = inspect_commissioning_bindings(bindings)
        self.assertEqual(result["unexpected_provider_id_fields"], ("unreviewed",))
        self.assertFalse(result["complete_binding_inventory"])

    def test_whitespace_provider_identity_denied(self):
        bindings = {name: object() for name in REQUIRED_BINDINGS}
        bindings["reviewed_provider_ids"] = {field: "id-" + field for field in REQUIRED}
        bindings["reviewed_provider_ids"][REQUIRED[0]] = " id "
        result = inspect_commissioning_bindings(bindings)
        self.assertIn(REQUIRED[0], result["missing_provider_id_fields"])
        self.assertFalse(result["complete_binding_inventory"])


if __name__ == "__main__":
    unittest.main()
