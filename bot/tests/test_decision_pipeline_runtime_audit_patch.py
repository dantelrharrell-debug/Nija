from types import SimpleNamespace
import sys
from types import ModuleType

from bot import decision_pipeline_runtime_patch as patch


def _reset_patch_state() -> None:
    with patch._STATE_LOCK:
        patch._REJECTION_COUNTS.clear()
        patch._LAST_ORDER_SUBMITTED_TS = 0.0
        patch._LAST_REJECTION_SUMMARY_TS = 0.0
        for key in list(patch._STAGE_HEARTBEATS.keys()):
            patch._STAGE_HEARTBEATS[key] = 0.0


def test_core_loop_emits_scan_start_and_complete(caplog) -> None:
    _reset_patch_state()

    class DummyCoreLoop:
        def run_scan_phase(self, *args, **kwargs):
            return SimpleNamespace(entries_taken=0, entries_blocked=1, symbols_scored=3)

    patch._patch_core_loop(DummyCoreLoop)

    with caplog.at_level("WARNING", logger="nija.decision_pipeline"):
        DummyCoreLoop().run_scan_phase(None, 0.0, ["BTC-USD", "ETH-USD"])

    assert "SCAN_STARTED" in caplog.text
    assert "MARKET_SCAN_COMPLETE" in caplog.text


def test_risk_rejection_logs_required_fields(caplog) -> None:
    _reset_patch_state()

    class DummyRiskEngine:
        def evaluate(self, **kwargs):
            return SimpleNamespace(final_decision="BLOCKED", block_reason="min_notional")

    patch._patch_risk_gate_class(DummyRiskEngine)

    with caplog.at_level("WARNING", logger="nija.decision_pipeline"):
        DummyRiskEngine().evaluate(symbol="SOL-USD", ai_threshold=12.0, ai_score=9.0)

    assert "MIN_NOTIONAL_REJECT" in caplog.text
    assert "SIGNAL_REJECTED" in caplog.text
    assert "symbol=SOL-USD" in caplog.text
    assert "exchange=unknown" in caplog.text
    assert "strategy=DummyRiskEngine" in caplog.text
    assert "reason=min_notional" in caplog.text
    assert "threshold=12.00000000" in caplog.text
    assert "actual_value=9.00000000" in caplog.text


def test_rejection_summary_emits_every_sixty_seconds(caplog) -> None:
    _reset_patch_state()
    with patch._STATE_LOCK:
        patch._REJECTION_COUNTS.update({"min_notional": 2, "spread_too_high": 1})

    with caplog.at_level("WARNING", logger="nija.decision_pipeline"):
        patch._emit_rejection_summary_if_due(now=120.0)

    assert "REJECTION_SUMMARY" in caplog.text
    assert "min_notional:2" in caplog.text
    assert "spread_too_high:1" in caplog.text


def test_three_venue_ready_uses_canonical_writer_status(monkeypatch) -> None:
    authority_module = ModuleType("bot.writer_authority")

    class _Status:
        ready = False

    class _WriterAuthority:
        @staticmethod
        def get_status(*_args, **_kwargs):
            return _Status()

    authority_module.WriterAuthority = _WriterAuthority
    monkeypatch.setitem(sys.modules, "bot.writer_authority", authority_module)
    monkeypatch.delenv("NIJA_WRITER_READY", raising=False)
    monkeypatch.setenv("NIJA_THREE_VENUE_EXECUTION_READY", "1")
    monkeypatch.setenv("NIJA_EXECUTION_ENABLED", "1")

    assert patch._is_three_venue_ready() is False
