from __future__ import annotations

import threading
from collections import deque
from types import SimpleNamespace

from bot import exchange_rejection_stale_latch_v226_patch as v226


class _Protector:
    def __init__(self, *, results=(), gates=None, triggered=True, provenance=()):
        self._cfg = SimpleNamespace(order_window_size=20)
        self._lock = threading.Lock()
        self._order_results = deque(results, maxlen=20)
        self._nija_order_result_provenance_v258 = deque(provenance, maxlen=20)
        self._status = {
            "triggered": triggered,
            "trigger_reason": "Order rejection rate 100.0% >= 50% (5/5 orders rejected)",
            "gates": gates or [
                {"gate": "order_rejection", "status": "green"},
                {"gate": "api_error_rate", "status": "green"},
                {"gate": "api_latency", "status": "green"},
            ],
        }

    def get_status(self):
        return dict(self._status)


def _local_record(index: int, reason: str = "ETH-USD not available on Kraken"):
    return {
        "timestamp": float(index),
        "order_id": f"local-{index}",
        "accepted": False,
        "kill_switch_module": "bot.exchange_kill_switch",
        "source": "execution_pipeline",
        "symbol": "ETH-USD",
        "side": "buy",
        "reason": reason,
        "known_non_exchange": False,
    }


def test_exact_persisted_5_of_5_signature_is_eligible(monkeypatch):
    protector = _Protector()
    monkeypatch.setattr(v226, "_minimum_samples", lambda _protector: 5)
    record = {
        "source": "EXCHANGE_MONITOR",
        "reason": "Exchange kill-switch: Order rejection rate 100.0% >= 50% (5/5 orders rejected)",
    }
    ok, detail = v226._exact_persisted_rejection_signature(record, protector)
    assert ok is True
    assert "5/5 orders rejected" in detail


def test_current_process_samples_block_legacy_recovery():
    protector = _Protector(results=(False, False, False, False, False))
    ok, detail = v226._protector_persisted_latch(protector, "unused")
    assert ok is False
    assert detail == "current_process_rejection_samples_present:5"


def test_nonorder_red_gate_blocks_recovery():
    protector = _Protector(
        gates=[
            {"gate": "order_rejection", "status": "green"},
            {"gate": "api_latency", "status": "red"},
        ]
    )
    ok, detail = v226._protector_persisted_latch(protector, "unused")
    assert ok is False
    assert detail == "current_exchange_gate_red:api_latency"


def test_manual_or_partial_rejection_signatures_are_preserved(monkeypatch):
    protector = _Protector()
    monkeypatch.setattr(v226, "_minimum_samples", lambda _protector: 5)
    manual = {
        "source": "MANUAL",
        "reason": "Exchange kill-switch: Order rejection rate 100.0% >= 50% (5/5 orders rejected)",
    }
    assert v226._exact_persisted_rejection_signature(manual, protector)[0] is False

    partial = {
        "source": "EXCHANGE_MONITOR",
        "reason": "Exchange kill-switch: Order rejection rate 60.0% >= 50% (3/5 orders rejected)",
    }
    assert v226._exact_persisted_rejection_signature(partial, protector)[0] is False


def test_v267_proves_five_reclassified_local_samples(monkeypatch):
    protector = _Protector(
        results=(False, False, False, False, False),
        provenance=tuple(_local_record(i) for i in range(5)),
    )
    monkeypatch.setattr(v226, "_minimum_samples", lambda _protector: 5)

    from bot import exchange_kill_switch_alias_provenance_v258_patch as v258
    monkeypatch.setattr(v258, "_is_non_exchange", lambda reason: "not available on kraken" in reason.lower())

    ok, detail, count = v226._current_window_false_positive_proof(protector)
    assert ok is True
    assert count == 5
    assert detail == "verified_non_exchange_current_window:5"


def test_v267_refuses_one_genuine_exchange_rejection(monkeypatch):
    records = [_local_record(i) for i in range(4)]
    records.append(_local_record(4, reason="Kraken AddOrder rejected: EOrder:Insufficient funds"))
    protector = _Protector(results=(False,) * 5, provenance=records)
    monkeypatch.setattr(v226, "_minimum_samples", lambda _protector: 5)

    from bot import exchange_kill_switch_alias_provenance_v258_patch as v258
    monkeypatch.setattr(v258, "_is_non_exchange", lambda reason: "not available on kraken" in reason.lower())

    ok, detail, count = v226._current_window_false_positive_proof(protector)
    assert ok is False
    assert count == 0
    assert detail.startswith("provenance_not_non_exchange:4:")


def test_v267_refuses_unknown_or_direct_legacy_source(monkeypatch):
    records = [_local_record(i) for i in range(5)]
    records[-1]["source"] = "direct_or_legacy"
    protector = _Protector(results=(False,) * 5, provenance=records)
    monkeypatch.setattr(v226, "_minimum_samples", lambda _protector: 5)

    from bot import exchange_kill_switch_alias_provenance_v258_patch as v258
    monkeypatch.setattr(v258, "_is_non_exchange", lambda _reason: True)

    ok, detail, count = v226._current_window_false_positive_proof(protector)
    assert ok is False
    assert count == 0
    assert detail == "provenance_source_not_execution_pipeline:4:direct_or_legacy"


def test_v267_refuses_provenance_tail_mismatch(monkeypatch):
    records = [_local_record(i) for i in range(5)]
    records[-1]["accepted"] = True
    protector = _Protector(results=(False,) * 5, provenance=records)
    monkeypatch.setattr(v226, "_minimum_samples", lambda _protector: 5)

    ok, detail, count = v226._current_window_false_positive_proof(protector)
    assert ok is False
    assert count == 0
    assert detail == "provenance_tail_not_aligned_with_current_window"


def test_v267_refuses_window_with_accepted_sample(monkeypatch):
    records = [_local_record(i) for i in range(5)]
    records[-1]["accepted"] = True
    protector = _Protector(results=(False, False, False, False, True), provenance=records)
    monkeypatch.setattr(v226, "_minimum_samples", lambda _protector: 5)

    ok, detail, count = v226._current_window_false_positive_proof(protector)
    assert ok is False
    assert count == 0
    assert detail == "current_window_contains_accepted_samples"


def test_v267_clears_only_unchanged_verified_window():
    protector = _Protector(results=(False,) * 5)
    ok, detail = v226._clear_verified_current_window(protector, 5)
    assert ok is True
    assert detail == "verified_current_window_cleared:5"
    assert list(protector._order_results) == []


def test_v267_clear_refuses_changed_window():
    protector = _Protector(results=(False, False, False, False, True))
    ok, detail = v226._clear_verified_current_window(protector, 5)
    assert ok is False
    assert detail == "current_window_changed_before_clear"
