import unittest

from bot.startup_runtime_safety import normalize_runtime_startup_env


class StartupRuntimeSafetyTests(unittest.TestCase):
    def test_live_mode_clears_unconfirmed_bypass_and_force_flags(self) -> None:
        env = {
            "DRY_RUN_MODE": "false",
            "PAPER_MODE": "false",
            "NIJA_UNSAFE_BYPASS_DISTRIBUTED_LOCK": "true",
            "NIJA_DISABLE_WRITER_LOCK": "1",
            "FORCE_TRADE": "true",
            "FORCE_TRADE_MODE": "true",
            "NIJA_FORCE_ACTIVATION": "1",
            "NIJA_SKIP_STARTUP_PHASE_GATE": "yes",
            "HF_SCALP_MODE": "false",
            "HF_FLIP_MODE": "false",
        }

        notes = normalize_runtime_startup_env(env)

        self.assertEqual(env["NIJA_UNSAFE_BYPASS_DISTRIBUTED_LOCK"], "0")
        self.assertEqual(env["NIJA_DISABLE_WRITER_LOCK"], "0")
        self.assertEqual(env["FORCE_TRADE"], "false")
        self.assertEqual(env["FORCE_TRADE_MODE"], "false")
        self.assertEqual(env["NIJA_FORCE_ACTIVATION"], "false")
        self.assertEqual(env["NIJA_SKIP_STARTUP_PHASE_GATE"], "false")
        self.assertEqual(env["HF_SCALP_MODE"], "1")
        self.assertEqual(env["HF_SCALPING_MODE"], "1")
        self.assertIn("cleared:NIJA_UNSAFE_BYPASS_DISTRIBUTED_LOCK", notes)
        self.assertIn("cleared:FORCE_TRADE", notes)
        self.assertIn("enabled:HF_SCALP_MODE", notes)

    def test_confirmed_live_bypass_is_preserved(self) -> None:
        env = {
            "DRY_RUN_MODE": "false",
            "PAPER_MODE": "false",
            "NIJA_CONFIRM_BYPASS_RISKS": "true",
            "NIJA_UNSAFE_BYPASS_DISTRIBUTED_LOCK": "true",
            "FORCE_TRADE": "true",
            "HF_SCALP_MODE": "0",
            "HF_FLIP_MODE": "1",
        }

        normalize_runtime_startup_env(env)

        self.assertEqual(env["NIJA_UNSAFE_BYPASS_DISTRIBUTED_LOCK"], "true")
        self.assertEqual(env["FORCE_TRADE"], "true")
        self.assertEqual(env["HF_SCALP_MODE"], "0")
        self.assertEqual(env["HF_SCALPING_MODE"], "0")

    def test_dry_run_does_not_rewrite_flags(self) -> None:
        env = {
            "DRY_RUN_MODE": "true",
            "PAPER_MODE": "false",
            "FORCE_TRADE": "true",
            "HF_SCALP_MODE": "false",
        }

        notes = normalize_runtime_startup_env(env)

        self.assertEqual(env["FORCE_TRADE"], "true")
        self.assertEqual(env["HF_SCALP_MODE"], "false")
        self.assertEqual(notes, [])


if __name__ == "__main__":
    unittest.main()
