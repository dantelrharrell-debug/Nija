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


def test_old_authenticated_kraken_close_backoff(monkeypatch):
    """An actual old final QueryOrders row must not repeatedly consume reads."""
    monkeypatch.setattr(v406, "_HISTORICAL_ORDER_RECHECK_AT", {})
    monkeypatch.setattr(v406, "_marker_ready", lambda: False)
    monkeypatch.setattr(v406, "_candidate_order_ids", lambda: ["HISTORICAL-ORDER"])
    monkeypatch.setattr(v406, "_recent_candidate_order_ids", lambda: [])
    state = {"mono": 200.0, "queries": 0}
    monkeypatch.setattr(v406.time, "time", lambda: 10000.0)
    monkeypatch.setattr(v406.time, "monotonic", lambda: state["mono"])

    def query(order_id):
        assert order_id == "HISTORICAL-ORDER"
        state["queries"] += 1
        return object(), {"status": "closed", "vol_exec": "0.12",
                          "cost": "320", "closetm": 7000.0}

    def no_promotion(*_args, **_kwargs):
        raise AssertionError("stale historical event cannot be promoted")

    monkeypatch.setattr(v406, "_final_authenticated_row", query)
    monkeypatch.setattr(v406, "_promote_same_authenticated_row", no_promotion)
    assert v406.recover_once() is False
    assert v406.recover_once() is False
    assert state["queries"] == 1
    state["mono"] = 801.0
    assert v406.recover_once() is False
    assert state["queries"] == 2


def test_new_order_not_blocked_by_different_stale_order(monkeypatch):
    """Backoff is per actual order ID, not a blanket freeze of recoveries."""
    monkeypatch.setattr(v406, "_HISTORICAL_ORDER_RECHECK_AT", {"OLD": 950.0})
    monkeypatch.setattr(v406, "_marker_ready", lambda: False)
    monkeypatch.setattr(v406, "_candidate_order_ids", lambda: ["NEW"])
    monkeypatch.setattr(v406, "_recent_candidate_order_ids", lambda: [])
    monkeypatch.setattr(v406.time, "time", lambda: 10000.0)
    monkeypatch.setattr(v406.time, "monotonic", lambda: 500.0)
    queried = []
    promoted = []

    def query(order_id):
        queried.append(order_id)
        return object(), {"status": "closed", "vol_exec": 0.2,
                          "cost": 500, "closetm": 9995.0}

    def promote(order_id, _broker, _row):
        promoted.append(order_id)
        return True, 1

    monkeypatch.setattr(v406, "_final_authenticated_row", query)
    monkeypatch.setattr(v406, "_promote_same_authenticated_row", promote)
    # False means no readiness flag was manufactured by this unit-test stub.
    assert v406.recover_once() is False
    assert queried == ["NEW"]
    assert promoted == ["NEW"]
    assert "NEW" not in v406._HISTORICAL_ORDER_RECHECK_AT


def test_missing_queryorders_closetm_never_promotes_or_guesses_age(monkeypatch):
    """Missing close time cannot be promoted or cached as proven stale."""
    monkeypatch.setattr(v406, "_HISTORICAL_ORDER_RECHECK_AT", {})
    monkeypatch.setattr(v406, "_marker_ready", lambda: False)
    monkeypatch.setattr(v406, "_candidate_order_ids", lambda: ["UNKNOWN-EPOCH"])
    monkeypatch.setattr(v406, "_recent_candidate_order_ids", lambda: [])
    count = {"queries": 0, "promotions": 0}

    def query(_order_id):
        count["queries"] += 1
        return object(), {"status": "closed", "vol_exec": 1,
                          "cost": 100}

    def promote(*_args, **_kwargs):
        count["promotions"] += 1
        return False, 0

    monkeypatch.setattr(v406, "_final_authenticated_row", query)
    monkeypatch.setattr(v406, "_promote_same_authenticated_row", promote)
    assert v406.recover_once() is False
    assert v406.recover_once() is False
    assert count == {"queries": 2, "promotions": 0}
    assert v406._HISTORICAL_ORDER_RECHECK_AT == {}



def test_candidate_skips_backed_off_order_and_recovers_next(monkeypatch):
    """A stale top candidate must not starve an eligible pending order."""
    class V363:
        @staticmethod
        def _load_pending():
            return {
                "NEWEST-BUT-OLD": {"last_seen_epoch": 30.0},
                "RECENT-UNCHECKED": {"last_seen_epoch": 20.0},
            }

    real_import = v406.importlib.import_module
    monkeypatch.setattr(
        v406.importlib, "import_module",
        lambda name: V363 if name == "bot.runtime_kraken_deferred_fill_proof_recovery_v363_patch" else real_import(name),
    )
    monkeypatch.setattr(v406, "_HISTORICAL_ORDER_RECHECK_AT", {"NEWEST-BUT-OLD": 900.0})
    monkeypatch.setattr(v406.time, "monotonic", lambda: 500.0)
    assert v406._candidate_order_id() == "RECENT-UNCHECKED"


def test_all_known_historical_pending_orders_skip_without_fallback(monkeypatch):
    """When all candidates are cooled down, do not query unrelated fallback."""
    class V363:
        @staticmethod
        def _load_pending():
            return {
                "OLD-A": {"last_seen_epoch": 30.0},
                "OLD-B": {"last_seen_epoch": 20.0},
            }

    real_import = v406.importlib.import_module
    monkeypatch.setattr(
        v406.importlib, "import_module",
        lambda name: V363 if name == "bot.runtime_kraken_deferred_fill_proof_recovery_v363_patch" else real_import(name),
    )
    monkeypatch.setattr(v406, "_HISTORICAL_ORDER_RECHECK_AT",
                        {"OLD-A": 900.0, "OLD-B": 950.0})
    monkeypatch.setattr(v406.time, "monotonic", lambda: 500.0)
    assert v406._candidate_order_id() == ""
    monkeypatch.setattr(v406, "_marker_ready", lambda: False)
    monkeypatch.setattr(v406, "_recent_candidate_order_ids", lambda: [])
    monkeypatch.setattr(
        v406, "_final_authenticated_row",
        lambda order_id: (_ for _ in ()).throw(
            AssertionError("no broker query for already classified historical orders")
        ),
    )
    assert v406.recover_once() is False
