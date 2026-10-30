import unittest
from unittest.mock import patch

from bot.kraken_six_source_binding_contract_v490 import EXPECTED_OWNERS, IndependentSourceBindingRequired
from bot.kraken_thirteen_source_reviewed_bridge_v491 import compose_reviewed_thirteen_source_registry


class ThirteenSourceBridgeTests(unittest.TestCase):
    def test_unreviewed_refused_before_composition(self):
        with self.assertRaises(IndependentSourceBindingRequired):
            compose_reviewed_thirteen_source_registry(
                broker_providers={}, protective_exit_provider=lambda: {},
                writer_nonce_providers={},
                independent_providers={k: (lambda: {}) for k in EXPECTED_OWNERS},
                reviewed_source_owners=EXPECTED_OWNERS,
                trusted_provider_ids={}, independently_reviewed=False,
            )

    def test_complete_bindings_forwarded_without_invoking(self):
        calls = []
        independent = {k: (lambda k=k: calls.append(k)) for k in EXPECTED_OWNERS}
        with patch("bot.kraken_thirteen_source_reviewed_bridge_v491.compose_seven_source_kraken_registry") as compose:
            compose.return_value = object()
            result = compose_reviewed_thirteen_source_registry(
                broker_providers={}, protective_exit_provider=lambda: {},
                writer_nonce_providers={}, independent_providers=independent,
                reviewed_source_owners=EXPECTED_OWNERS,
                trusted_provider_ids={}, independently_reviewed=True,
            )
            self.assertIs(result, compose.return_value)
            self.assertEqual(set(compose.call_args.kwargs["independent_providers"]), set(EXPECTED_OWNERS))
            self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
