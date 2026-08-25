from __future__ import annotations

import threading
from types import SimpleNamespace

from bot import exchange_rejection_stale_latch_v226_patch as v226


class _Protector:
    def __init__(self, *, results=(), gates=None, triggered=True):
        self._cfg = SimpleNamespace(order_window_size=20)
        self._lock = threading.Lock()
        self._order_results = list(results)
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


def test_current_process_samples_block_recovery():
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
