from __future__ import annotations

from bot import runtime_known_execution_probe_revalidation_v406_patch as v406


def test_candidate_order_prefers_newest_pending(monkeypatch):
    class V363:
        @staticmethod
        def _load_pending():
            return {
                "OLD": {"last_seen_epoch": 10.0},
                "NEW": {"last_seen_epoch": 20.0},
            }

    real_import = v406.importlib.import_module
    monkeypatch.setattr(
        v406.importlib,
        "import_module",
        lambda name: V363 if name == "bot.runtime_kraken_deferred_fill_proof_recovery_v363_patch" else real_import(name),
    )
    assert v406._candidate_order_id() == "NEW"


def test_candidate_order_falls_back_when_pending_empty(monkeypatch):
    class V363:
        @staticmethod
        def _load_pending():
            return {}

    real_import = v406.importlib.import_module
    monkeypatch.setattr(
        v406.importlib,
        "import_module",
        lambda name: V363 if name == "bot.runtime_kraken_deferred_fill_proof_recovery_v363_patch" else real_import(name),
    )
    assert v406._candidate_order_id() == v406._FALLBACK_ORDER_ID
