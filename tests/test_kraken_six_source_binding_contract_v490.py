import unittest

from bot.kraken_six_source_binding_contract_v490 import (
    EXPECTED_OWNERS,
    IndependentSourceBindingRequired,
    validate_six_source_bindings,
)


class SixSourceContractTests(unittest.TestCase):
    def setUp(self):
        self.providers = {name: (lambda: {}) for name in EXPECTED_OWNERS}
        self.owners = dict(EXPECTED_OWNERS)

    def test_refuses_unreviewed(self):
        with self.assertRaises(IndependentSourceBindingRequired):
            validate_six_source_bindings(
                self.providers, reviewed_source_owners=self.owners
            )

    def test_refuses_missing_provider(self):
        providers = dict(self.providers)
        providers.pop("risk_limits")
        with self.assertRaises(IndependentSourceBindingRequired):
            validate_six_source_bindings(
                providers, reviewed_source_owners=self.owners,
                independently_reviewed=True,
            )

    def test_refuses_owner_mismatch(self):
        owners = dict(self.owners)
        owners["operator_authorization"] = "risk_governor"
        with self.assertRaises(IndependentSourceBindingRequired):
            validate_six_source_bindings(
                self.providers, reviewed_source_owners=owners,
                independently_reviewed=True,
            )

    def test_accepts_only_complete_structural_contract_without_invocation(self):
        called = []
        providers = {field: (lambda field=field: called.append(field))
                     for field in EXPECTED_OWNERS}
        result = validate_six_source_bindings(
            providers, reviewed_source_owners=self.owners,
            independently_reviewed=True,
        )
        self.assertEqual(set(result), set(EXPECTED_OWNERS))
        self.assertEqual(called, [])


if __name__ == "__main__":
    unittest.main()
