from __future__ import annotations

import types

import bot.production_readiness_v39_patch as v39


def test_okx_boundary_normalizes_usdtt_before_dispatch():
    seen = {}

    class OKXRestClient:
        __module__ = "bot.fake_okx"
        BASE_URL = "https://www.okx.com"

        def _request(self, method, path, *, params=None, payload=None, private=False):
            seen["params"] = dict(params or {})
            seen["payload"] = dict(payload or {}) if isinstance(payload, dict) else payload
            return {"code": "0", "data": []}

    assert v39._wrap_okx_rest_class(OKXRestClient, "bot.fake_okx") is True
    client = OKXRestClient()
    result = client._request(
        "GET",
        "/api/v5/market/candles",
        params={"instId": "LRC-USDTT", "bar": "1m"},
    )

    assert result["code"] == "0"
    assert seen["params"]["instId"] == "LRC-USDT"
    assert v39._malformed_okx_inst_id(seen["params"]["instId"]) is False


def test_okx_normalizer_is_idempotent_for_valid_usdt():
    assert v39._normalize_okx_inst_id("LRC-USDT") == "LRC-USDT"
    assert v39._normalize_okx_inst_id("LRC-USDTT") == "LRC-USDT"
    assert v39._normalize_okx_inst_id("BTCUSDT") == "BTC-USDT"


def test_only_missing_lock_fencing_mismatch_is_inprocess_recoverable():
    assert v39._recoverable_writer_loss("lock_missing_and_fencing_token_mismatch") is True
    assert v39._recoverable_writer_loss(
        "entrypoint_writer_authority_lost:lock_missing_and_fencing_token_mismatch"
    ) is True
    assert v39._recoverable_writer_loss("lock_owned_by_different_writer") is False
    assert v39._recoverable_writer_loss("heartbeat_grace_expired:redis_timeout") is False


def test_terminal_stop_file_prevents_seak_resume(monkeypatch):
    monkeypatch.setattr(v39, "_terminal_stop_files_present", lambda: True)

    class FakeSEAK:
        is_halted = True
        _halt_reason = "entrypoint_writer_authority_lost:lock_missing_and_fencing_token_mismatch"

        def resume(self, caller="operator"):
            raise AssertionError("resume must not be called while emergency-stop files exist")

    fake_module = types.SimpleNamespace(get_seak=lambda: FakeSEAK())
    real_import = v39.importlib.import_module

    def fake_import(name, package=None):
        if name == "bot.single_execution_authority_kernel":
            return fake_module
        return real_import(name, package)

    monkeypatch.setattr(v39.importlib, "import_module", fake_import)
    assert v39._resume_seak_if_writer_halt() is False


def test_writer_loss_callback_preserves_shutdown_for_nonrecoverable_reason(monkeypatch):
    shutdown_reasons = []

    class Runtime:
        def __init__(self):
            self._on_lost_callback = lambda reason: shutdown_reasons.append(reason)
            self.callback = None

        def set_on_lost_callback(self, callback):
            self.callback = callback

    runtime = Runtime()
    module = types.ModuleType("bot.bot_main")
    module._writer_authority_runtime = runtime
    module._authority_heartbeat_monitor = None
    module._core_loop_thread = None
    module._acquire_writer_authority_before_nonce = lambda: True
    module._keep_process_alive_after_loop_return = lambda: None
    module.SUPERVISOR_POLL_INTERVAL_S = 0.25

    monkeypatch.setattr(v39, "_RECOVERY_ACTIVE", False)
    assert v39._patch_bot_main(module) is True
    assert module._acquire_writer_authority_before_nonce() is True
    assert callable(runtime.callback)

    runtime.callback("lock_owned_by_different_writer")
    assert shutdown_reasons == ["lock_owned_by_different_writer"]


def test_writer_loss_callback_starts_bounded_recovery_for_missing_lock(monkeypatch):
    shutdown_reasons = []
    recovery_calls = []

    class Runtime:
        def __init__(self):
            self._on_lost_callback = lambda reason: shutdown_reasons.append(reason)
            self.callback = None

        def set_on_lost_callback(self, callback):
            self.callback = callback

    runtime = Runtime()
    module = types.ModuleType("bot.bot_main")
    module._writer_authority_runtime = runtime
    module._authority_heartbeat_monitor = None
    module._core_loop_thread = None
    module._acquire_writer_authority_before_nonce = lambda: True
    module._keep_process_alive_after_loop_return = lambda: None
    module.SUPERVISOR_POLL_INTERVAL_S = 0.25

    monkeypatch.setattr(
        v39,
        "_start_writer_recovery",
        lambda bot_main, rt, reason, fallback: recovery_calls.append((bot_main, rt, reason)) or True,
    )

    assert v39._patch_bot_main(module) is True
    assert module._acquire_writer_authority_before_nonce() is True
    runtime.callback("lock_missing_and_fencing_token_mismatch")

    assert shutdown_reasons == []
    assert len(recovery_calls) == 1
    assert recovery_calls[0][1] is runtime
    assert recovery_calls[0][2] == "lock_missing_and_fencing_token_mismatch"


def test_kraken_recovery_coordinator_is_retriggered(monkeypatch):
    calls = []
    fake_module = types.SimpleNamespace(
        _start_kraken_recovery_coordinator=lambda: calls.append("start") or True
    )
    real_import = v39.importlib.import_module

    def fake_import(name, package=None):
        if name == "bot.canonical_broker_startup_convergence_v24":
            return fake_module
        return real_import(name, package)

    monkeypatch.setattr(v39.importlib, "import_module", fake_import)
    v39._kick_kraken_recovery()
    assert calls == ["start"]
