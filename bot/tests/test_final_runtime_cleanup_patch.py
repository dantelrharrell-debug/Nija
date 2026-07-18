from __future__ import annotations

import importlib
import logging
import os
import sys
import threading
from dataclasses import dataclass
from types import ModuleType, SimpleNamespace


cleanup = importlib.import_module("bot.final_runtime_cleanup_patch")


def test_obsolete_runtime_watchdog_thread_is_suppressed(monkeypatch):
    calls: list[str] = []

    def fake_start(self, *args, **kwargs):
        calls.append(self.name)
        return "started"

    monkeypatch.setattr(threading.Thread, "start", fake_start)
    cleanup._ORIGINAL_THREAD_START = None
    cleanup._install_thread_quiescence()

    blocked = threading.Thread(target=lambda: None, name="ScanOwnerAuthConvergenceWatchdog")
    allowed = threading.Thread(target=lambda: None, name="authority-heartbeat-monitor")

    assert blocked.start() is None
    assert allowed.start() == "started"
    assert calls == ["authority-heartbeat-monitor"]


def test_okx_isolated_until_balance_is_observed(monkeypatch):
    for key in (
        "NIJA_OKX_CONNECTED",
        "NIJA_OKX_TRADING_READY",
        "NIJA_OKX_ACTIVATED",
        "NIJA_OKX_BALANCE_OBSERVED",
        "NIJA_OKX_TRADING_SPENDABLE",
        "NIJA_OKX_SPENDABLE_QUOTE",
    ):
        monkeypatch.delenv(key, raising=False)

    ready, reason, spendable = cleanup._okx_ready()
    assert ready is False
    assert reason == "not_connected"
    assert spendable == 0.0
    assert os.environ["NIJA_OKX_ENTRY_ISOLATED"] == "1"

    monkeypatch.setenv("NIJA_OKX_CONNECTED", "1")
    monkeypatch.setenv("NIJA_OKX_TRADING_READY", "1")
    monkeypatch.setenv("NIJA_OKX_ACTIVATED", "1")
    monkeypatch.setenv("NIJA_OKX_BALANCE_OBSERVED", "1")
    monkeypatch.setenv("NIJA_OKX_TRADING_SPENDABLE", "25")

    ready, reason, spendable = cleanup._okx_ready()
    assert ready is True
    assert reason == "ready"
    assert spendable == 25.0
    assert os.environ["NIJA_OKX_ENTRY_ISOLATED"] == "0"


def test_execution_pipeline_emits_attempt_ack_and_fill(monkeypatch, caplog):
    module = ModuleType("bot.execution_pipeline")

    @dataclass
    class PipelineResult:
        success: bool
        symbol: str
        side: str
        size_usd: float
        error: str = ""
        latency_ms: float = 0.0
        order_id: str = ""
        status: str = ""
        fill_price: float = 0.0
        filled_quantity: float = 0.0

    class ExecutionPipeline:
        def execute(self, request):
            return PipelineResult(
                success=True,
                symbol=request.symbol,
                side=request.side,
                size_usd=request.size_usd,
                order_id="abc123",
                status="filled",
                fill_price=12.5,
                filled_quantity=2.0,
            )

    module.PipelineResult = PipelineResult
    module.ExecutionPipeline = ExecutionPipeline
    assert cleanup._patch_execution_pipeline(module) is True

    request = SimpleNamespace(
        symbol="SOL-USD",
        side="buy",
        size_usd=25.0,
        preferred_broker="kraken",
        intent_type="entry",
        intent_id="intent-1",
        reduce_only=False,
    )

    with caplog.at_level(logging.CRITICAL):
        result = ExecutionPipeline().execute(request)

    assert result.success is True
    text = "\n".join(record.getMessage() for record in caplog.records)
    assert "ORDER_ATTEMPT" in text
    assert "BROKER_ACK" in text
    assert "ORDER_FILLED" in text


def test_unobserved_okx_entry_is_rejected_before_original_execute(monkeypatch):
    module = ModuleType("bot.execution_pipeline")
    calls = []

    @dataclass
    class PipelineResult:
        success: bool
        symbol: str
        side: str
        size_usd: float
        error: str = ""
        latency_ms: float = 0.0

    class ExecutionPipeline:
        def execute(self, request):
            calls.append(request)
            return PipelineResult(True, request.symbol, request.side, request.size_usd)

    module.PipelineResult = PipelineResult
    module.ExecutionPipeline = ExecutionPipeline
    monkeypatch.setenv("NIJA_OKX_CONNECTED", "0")
    monkeypatch.setenv("NIJA_OKX_TRADING_READY", "0")
    monkeypatch.setenv("NIJA_OKX_ACTIVATED", "0")
    monkeypatch.setenv("NIJA_OKX_BALANCE_OBSERVED", "0")
    assert cleanup._patch_execution_pipeline(module) is True

    request = SimpleNamespace(
        symbol="SOL-USDT",
        side="buy",
        size_usd=10.0,
        preferred_broker="okx",
        intent_type="entry",
        reduce_only=False,
    )
    result = ExecutionPipeline().execute(request)
    assert result.success is False
    assert result.error.startswith("okx_entry_isolated:")
    assert calls == []


def test_prebot_runtime_is_bridged_across_both_import_aliases(monkeypatch):
    bridge = importlib.import_module("prebot_writer_authority_fail_closed")
    runtime = object()
    canonical = ModuleType("bot.entrypoint_writer_authority")
    duplicate = ModuleType("entrypoint_writer_authority")

    monkeypatch.setitem(sys.modules, "bot.entrypoint_writer_authority", canonical)
    monkeypatch.setitem(sys.modules, "entrypoint_writer_authority", duplicate)
    monkeypatch.delenv("NIJA_WRITER_AUTHORITY_SINGLETON_BRIDGED", raising=False)

    bridge._bridge_canonical_runtime(runtime)

    assert sys.modules["bot.entrypoint_writer_authority"] is canonical
    assert sys.modules["entrypoint_writer_authority"] is canonical
    assert canonical.get_entrypoint_writer_authority() is runtime
    assert canonical._SINGLETON is runtime
    assert os.environ["NIJA_WRITER_AUTHORITY_SINGLETON_BRIDGED"] == "1"


def test_reentrant_repair_does_not_start_background_thread(monkeypatch):
    repair = importlib.import_module("reentrant_scan_owner_repair")
    calls: list[str] = []

    monkeypatch.setattr(repair, "_INSTALLED", False)
    monkeypatch.setattr(repair, "_repair_loaded", lambda: True)
    monkeypatch.setattr(threading.Thread, "start", lambda self: calls.append(self.name))

    repair.install()

    assert calls == []
