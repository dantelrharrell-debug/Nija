"""Safety regressions for read-only Kraken multi-candidate recovery."""
import importlib
import unittest
from unittest.mock import patch

MODULE = "bot.runtime_known_execution_probe_revalidation_v406_patch"


class TestRecoveryCandidates(unittest.TestCase):
    def test_worker_resumes_discovery_after_fresh_proof_expires(self):
        module = importlib.import_module(MODULE)
        # First pulse recovers genuine evidence; second sees it fresh; third
        # sees expiry. Success must not terminate the only recovery worker.
        with patch.object(module, "_marker_ready", side_effect=[False, True, False]), \
             patch.object(module, "_recent_candidate_order_ids", return_value=["candidate"]) as discover, \
             patch.object(module, "_candidate_order_ids", return_value=[]), \
             patch.object(module, "_recover_candidate", return_value=True) as recover, \
             patch.object(module.time, "sleep", side_effect=[None, None, SystemExit]) as sleep:
            with self.assertRaises(SystemExit):
                module._worker()
            self.assertEqual(discover.call_count, 2)
            self.assertEqual(recover.call_count, 2)
            self.assertEqual([call.args[0] for call in sleep.call_args_list], [10.0] * 3)

    def test_worker_retries_after_probe_exception(self):
        module = importlib.import_module(MODULE)
        with patch.object(module, "recover_once", side_effect=[RuntimeError("unavailable"), False]) as recover, \
             patch.object(module.time, "sleep", side_effect=[None, SystemExit]):
            with self.assertRaises(SystemExit):
                module._worker()
            self.assertEqual(recover.call_count, 2)

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
