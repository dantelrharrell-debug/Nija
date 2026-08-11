"""Regression checks for production authority paths that must never fail open."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _source(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_active_capital_has_no_synthetic_fail_open_balance() -> None:
    source = _source("bot/capital/active_capital.py")

    assert "999999.0" not in source
    assert "_force_trade_bypass" not in source


def test_execution_pipeline_never_bypasses_runtime_authority() -> None:
    source = _source("bot/execution_pipeline.py")

    assert "Bypassing assert_execution_dispatch_permitted" not in source
    assert "FORCE_TRADE_BYPASS dispatch_enabled=False" not in source
    assert "bypassing fencing token requirement" not in source.lower()
    assert "canonical writer fencing token missing" in source
    assert 'raise RuntimeError("execution authority module unavailable")' in source
    assert "dispatch_enabled = False" in source
    assert "self._ecel_required = True" in source
    assert "self._ecel_fail_closed = True" in source
    assert "NIJA_ECEL_REQUIRED=false" not in source
    assert "risk check skipped" not in source
    assert "BLOCKED_GLOBAL_RISK_UNAVAILABLE" in source


def test_execution_engine_fails_closed_when_bootstrap_authority_errors() -> None:
    source = _source("bot/execution_engine.py")

    assert "bootstrap authority check failed" in source
    assert "Bootstrap execution authority check skipped (non-fatal)" not in source
    assert "FORCE_TRADE_MODE: bool = False" in source
    assert "if not FORCE_TRADE_MODE" not in source
    assert 'os.getenv("ALLOW_SMALL_ORDERS", "false")' in source
    assert 'os.getenv("ALLOW_SMALL_ACCOUNT_TRADING", "false")' in source
    assert "On error, accept the trade" not in source


def test_direct_submitter_always_requires_distributed_writer() -> None:
    source = _source("bot/pipeline_order_submitter.py")
    gate = source.index("def submit_market_order_via_pipeline")
    request = source.index("PipelineRequest(", gate)
    guarded_region = source[gate:request]

    assert "assert_distributed_writer_authority()" in guarded_region
    assert 'if not (_truthy("FORCE_TRADE")' not in guarded_region
    assert 'raise RuntimeError("execution authority module unavailable")' in source


def test_broker_adapter_authority_fallbacks_fail_closed() -> None:
    source = _source("bot/broker_integration.py")

    assert source.count(
        'raise ExecutionBlocked("execution authority module unavailable")'
    ) >= 3


def test_nonce_and_multi_asset_authority_fallbacks_fail_closed() -> None:
    assert 'raise RuntimeError("startup write authority module unavailable")' in _source(
        "bot/distributed_nonce_manager.py"
    )
    assert 'raise RuntimeError("startup write authority module unavailable")' in _source(
        "bot/global_kraken_nonce.py"
    )
    assert 'raise RuntimeError("execution authority module unavailable")' in _source(
        "bot/multi_asset_executor.py"
    )


def test_live_sanitizers_do_not_depend_on_redis_being_preconfigured() -> None:
    strict_source = _source("bot/strict_live_startup_sanitizer.py")
    guard_source = _source("bot/live_redis_execution_bypass_guard.py")

    assert "if not _live_mode():" in strict_source
    assert "if not _live_mode():" in guard_source
    assert "if not _redis_configured():" not in strict_source
    assert "if not _redis_configured():" not in guard_source
    assert "builtins.__import__" not in guard_source
    assert "def _wrap_class" not in guard_source


def test_bot_package_import_does_not_install_runtime_monkeypatches() -> None:
    source = _source("bot/__init__.py")

    assert "_PATCH_HOOKS" not in source
    assert "install_import_hook" not in source
    assert 'import_module("sitecustomize")' not in source
    assert "runtime_import_hooks=false" in source


def test_activation_convergence_monkeypatch_is_retired_into_owners() -> None:
    patch_source = _source("bot/activation_convergence_v17_patch.py")
    heartbeat_source = _source("bot/authority_heartbeat.py")
    coordinator_source = _source("bot/startup_coordinator.py")

    assert "builtins.__import__" not in patch_source
    assert "runtime_monkeypatch=false" in patch_source
    assert "process-local writer fallback cannot satisfy live authority" in heartbeat_source
    assert "entrypoint writer renewal health proof unavailable" in heartbeat_source
    assert 'capital_state in {"READY", "RUNNING"}' in coordinator_source


def test_local_writer_watchdog_marks_fallback_lost() -> None:
    source = _source("bot/writer_distributed_loss_watchdog_v52_patch.py")

    assert '_mark_lost(runtime, "local_writer_fallback_forbidden")' in source
    assert 'state="local_fallback_forbidden"' in source


def test_core_thread_handoff_is_mandatory_and_observable() -> None:
    source = _source("bot/bot_main.py")

    assert "Canonical writer runtime missing before core-loop handoff" in source
    assert "Canonical writer runtime cannot register the core thread" in source
    assert "CANONICAL_CORE_THREAD_REGISTERED" in source


def test_live_readiness_cannot_be_fabricated() -> None:
    capital = _source("bot/capital_authority.py")
    assert "FORCE_SYSTEM_READY" not in capital
    assert "_maybe_auto_enable_live_mode" not in capital
    assert 'os.environ["LIVE_CAPITAL_VERIFIED"] = "true"' not in capital
    assert '"NIJA_CAPITAL_OPPORTUNISTIC", "false"' in capital
    assert '"NIJA_SINGLE_BROKER_MODE", "false"' in capital
    assert "FORCE_SYSTEM_READY" not in _source("bot/broker_manager.py")
    assert "NIJA_AUTO_CLEAR_EMERGENCY_STOP" not in _source("bot/kill_switch.py")


def test_live_capital_gate_overrides_are_simulation_only() -> None:
    manager = _source("bot/broker_manager.py")
    profiles = _source("bot/broker_profiles.py")

    assert "_SIMULATION_MODE" in manager
    assert "_SIMULATION_MODE" in profiles
    assert "os.getenv('NIJA_PLATFORM_LIFT_CAPITAL_GATES', 'false')" in manager
    assert "or (NIJA_PLATFORM_TRADING_ENABLED and _is_platform_acct)" not in manager
    assert "or (NIJA_PLATFORM_TRADING_ENABLED and _is_platform_order)" not in manager
    assert '"risk_mode": "active"' in profiles


def test_broker_risk_adapters_do_not_bypass_live_risk() -> None:
    plugins = _source("bot/risk_plugin_base.py")
    adapters = _source("bot/risk_sizing_adapter.py")
    registry = _source("bot/broker_isolation_registry.py")

    assert "MICRO_CAP_COINBASE_BYPASS" not in plugins
    assert "return ActiveRiskPlugin().evaluate(context)" in plugins
    assert adapters.count("return ActiveRiskPlugin().evaluate(context)") >= 4
    assert "KRAKEN_ISOLATED: no new entries" not in adapters
    assert "def skip_risk_gate" in registry
    assert "def log_risk_only" in registry
    global_controller = _source("bot/global_controller.py")
    assert "MICRO_CAP_COINBASE_BYPASS" not in global_controller
    assert "Kraken isolated mode — NO EXECUTION" not in global_controller


def test_hard_controls_compatibility_patch_is_retired() -> None:
    source = _source("bot/hard_controls_csm_repair_patch.py")

    assert "def _patched_can_trade" not in source
    assert "importlib.import_module =" not in source
    assert "runtime_monkeypatch=false" in source


def test_all_live_sanitizers_clear_capital_and_readiness_overrides() -> None:
    for relative in (
        "bot/__init__.py",
        "bot/strict_live_startup_sanitizer.py",
        "bot/live_redis_execution_bypass_guard.py",
        "bot/startup_runtime_safety.py",
    ):
        source = _source(relative)
        assert "FORCE_SYSTEM_READY" in source
        assert "NIJA_KRAKEN_TEST_LIFT_CAPITAL_GATES" in source
        assert "NIJA_PLATFORM_LIFT_CAPITAL_GATES" in source
        assert "COINBASE_IGNORE_GLOBAL_CAPITAL_FLOOR" in source
        assert "NIJA_CAPITAL_OPPORTUNISTIC" in source
