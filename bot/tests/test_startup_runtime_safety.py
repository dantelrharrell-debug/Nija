import unittest

from bot.startup_runtime_safety import normalize_runtime_startup_env


class StartupRuntimeSafetyTests(unittest.TestCase):
    def test_live_mode_clears_unconfirmed_bypass_and_activation_flags(self) -> None:
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
        self.assertEqual(env["FORCE_TRADE"], "true")
        self.assertEqual(env["FORCE_TRADE_MODE"], "true")
        self.assertEqual(env["NIJA_FORCE_ACTIVATION"], "false")
        self.assertEqual(env["NIJA_SKIP_STARTUP_PHASE_GATE"], "false")
        self.assertEqual(env["HF_SCALP_MODE"], "1")
        self.assertEqual(env["HF_SCALPING_MODE"], "1")
        self.assertIn("cleared:NIJA_UNSAFE_BYPASS_DISTRIBUTED_LOCK", notes)
        self.assertIn("enabled:HF_SCALP_MODE", notes)
        self.assertNotIn("cleared:FORCE_TRADE", notes)

    def test_confirmed_live_bypass_is_preserved_without_redis_endpoint(self) -> None:
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

    def test_live_redis_clears_even_confirmed_and_emergency_bypass_flags(self) -> None:
        env = {
            "DRY_RUN_MODE": "false",
            "PAPER_MODE": "false",
            "REDIS_URL": "redis://example.invalid:6379/0",
            "NIJA_CONFIRM_BYPASS_RISKS": "true",
            "NIJA_UNSAFE_BYPASS_DISTRIBUTED_LOCK": "true",
            "NIJA_DISABLE_WRITER_LOCK": "true",
            "NIJA_ALLOW_LOCAL_WRITER_LOCK_FALLBACK": "true",
            "NIJA_FORCE_LOCAL_WRITER_LOCK_FALLBACK": "true",
            "NIJA_ALLOW_DEGRADED_WRITER_AUTHORITY": "true",
            "NIJA_ALLOW_REDIS_DEGRADED": "true",
            "NIJA_EMERGENCY_LOCAL_FALLBACK_ACTIVE": "true",
            "NIJA_STRICT_REDIS_LEASE": "0",
            "NIJA_REQUIRE_DISTRIBUTED_LOCK": "false",
            "NIJA_RUNTIME_DEGRADED_MODE": "true",
            "NIJA_FAIL_CLOSED_MAX_RETRY_ATTEMPTS": "0",
            "FORCE_TRADE": "true",
            "HF_SCALP_MODE": "1",
        }

        notes = normalize_runtime_startup_env(env)

        self.assertEqual(env["NIJA_CONFIRM_BYPASS_RISKS"], "false")
        self.assertEqual(env["NIJA_UNSAFE_BYPASS_DISTRIBUTED_LOCK"], "0")
        self.assertEqual(env["NIJA_DISABLE_WRITER_LOCK"], "0")
        self.assertEqual(env["NIJA_ALLOW_LOCAL_WRITER_LOCK_FALLBACK"], "0")
        self.assertEqual(env["NIJA_FORCE_LOCAL_WRITER_LOCK_FALLBACK"], "0")
        self.assertEqual(env["NIJA_ALLOW_DEGRADED_WRITER_AUTHORITY"], "false")
        self.assertEqual(env["NIJA_ALLOW_REDIS_DEGRADED"], "false")
        self.assertEqual(env["NIJA_EMERGENCY_LOCAL_FALLBACK_ACTIVE"], "false")
        self.assertEqual(env["NIJA_STRICT_REDIS_LEASE"], "1")
        self.assertEqual(env["NIJA_REQUIRE_DISTRIBUTED_LOCK"], "true")
        self.assertEqual(env["NIJA_STRICT_WRITER_LOCK"], "true")
        self.assertEqual(env["NIJA_RUNTIME_DEGRADED_MODE"], "false")
        self.assertEqual(env["NIJA_FAIL_CLOSED_MAX_RETRY_ATTEMPTS"], "12")
        self.assertEqual(env["FORCE_TRADE"], "true")
        self.assertIn("cleared:NIJA_CONFIRM_BYPASS_RISKS", notes)
        self.assertIn("set:NIJA_STRICT_REDIS_LEASE=1", notes)

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
