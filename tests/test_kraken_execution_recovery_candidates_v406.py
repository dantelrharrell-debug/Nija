"""Safety regressions for read-only Kraken multi-candidate recovery."""
import importlib
import unittest
from unittest.mock import patch

MODULE = "bot.runtime_known_execution_probe_revalidation_v406_patch"


class TestRecoveryCandidates(unittest.TestCase):
    def test_scans_next_candidate_after_stale_or_unavailable(self):
        module = importlib.import_module(MODULE)
        with patch.object(module, "_marker_ready", return_value=False), \
             patch.object(module, "_recent_candidate_order_ids", return_value=[]), \
             patch.object(module, "_candidate_order_ids", return_value=["old", "new"]), \
             patch.object(module, "_recover_candidate", side_effect=[False, True]) as recover:
            self.assertTrue(module.recover_once())
            self.assertEqual([call.args[0] for call in recover.call_args_list], ["old", "new"])

    def test_no_candidate_never_authorizes(self):
        module = importlib.import_module(MODULE)
        with patch.object(module, "_marker_ready", return_value=False), \
             patch.object(module, "_recent_candidate_order_ids", return_value=[]), \
             patch.object(module, "_candidate_order_ids", return_value=[]), \
             patch.object(module, "_recover_candidate") as recover:
            self.assertFalse(module.recover_once())
            recover.assert_not_called()

    def test_missing_close_time_is_not_promoted(self):
        module = importlib.import_module(MODULE)
        row = {"status": "closed", "vol_exec": "1", "cost": "10"}
        with patch.object(module, "_final_authenticated_row", return_value=(object(), row)), \
             patch.object(module, "_promote_same_authenticated_row") as promote:
            self.assertFalse(module._recover_candidate("missing"))
            promote.assert_not_called()

    def test_future_close_time_is_not_promoted(self):
        module = importlib.import_module(MODULE)
        row = {"status": "closed", "closetm": 9999999999, "vol_exec": "1", "cost": "10"}
        with patch.object(module, "_final_authenticated_row", return_value=(object(), row)), \
             patch.object(module, "_promote_same_authenticated_row") as promote:
            self.assertFalse(module._recover_candidate("future"))
            promote.assert_not_called()

    def test_stale_authenticated_close_is_not_promoted(self):
        module = importlib.import_module(MODULE)
        with patch.object(module, "_final_authenticated_row", return_value=(object(), {"closetm": 1})), \
             patch.object(module, "_promote_same_authenticated_row") as promote:
            self.assertFalse(module._recover_candidate("old"))
            promote.assert_not_called()


if __name__ == "__main__":
    unittest.main()
