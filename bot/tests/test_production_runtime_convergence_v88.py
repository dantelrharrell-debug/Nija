from __future__ import annotations

import logging
import types

from bot import production_runtime_convergence_v88_patch as v88


def test_generic_execute_false_counts_are_classified_separately() -> None:
    assert v88._only_generic_execution_false_counts({"execute_action_returned_false": 5}) is True
    assert v88._only_generic_execution_false_counts({"returned_false_or_none": 2}) is True
    assert v88._only_generic_execution_false_counts({"execute_action_returned_none": 1}) is True


def test_real_rejection_reason_is_never_reclassified() -> None:
    assert v88._only_generic_execution_false_counts({"exchange_rejected": 1}) is False
    assert v88._only_generic_execution_false_counts({
        "execute_action_returned_false": 5,
        "exchange_rejected": 1,
    }) is False


def test_clear_generic_counts_preserves_real_rejections() -> None:
    tsm = types.SimpleNamespace(
        _EXECUTION_CIRCUIT_BREAKER_LOCK=__import__("threading").Lock(),
        _EXECUTION_CIRCUIT_BREAKER_COUNTS={
            "execute_action_returned_false": 5,
            "exchange_rejected": 1,
        },
        _EXECUTION_CIRCUIT_BREAKER_TRIPPED=True,
        _EXECUTION_CIRCUIT_BREAKER_REASON="exchange_rejected",
    )
    assert v88._clear_generic_execution_false_counts(tsm) == {}
    assert tsm._EXECUTION_CIRCUIT_BREAKER_COUNTS["exchange_rejected"] == 1
    assert tsm._EXECUTION_CIRCUIT_BREAKER_TRIPPED is True


def test_stale_startup_filter_only_hides_expired_live_active_message() -> None:
    filt = v88._StaleStartupSuppressionFilter()

    stale = logging.LogRecord(
        "nija.final_production_activation_repair_v58",
        logging.CRITICAL,
        __file__,
        1,
        "WRITER_RELEASE_SUPPRESSED_DURING_CANONICAL_STARTUP elapsed_s=2951.1 timeout_s=360.0 state=LIVE_ACTIVE",
        (),
        None,
    )
    current = logging.LogRecord(
        "nija.final_production_activation_repair_v58",
        logging.CRITICAL,
        __file__,
        1,
        "WRITER_RELEASE_SUPPRESSED_DURING_CANONICAL_STARTUP elapsed_s=120.0 timeout_s=360.0 state=LIVE_ACTIVE",
        (),
        None,
    )
    non_live = logging.LogRecord(
        "nija.final_production_activation_repair_v58",
        logging.CRITICAL,
        __file__,
        1,
        "WRITER_RELEASE_SUPPRESSED_DURING_CANONICAL_STARTUP elapsed_s=2951.1 timeout_s=360.0 state=LIVE_PENDING_CONFIRMATION",
        (),
        None,
    )

    assert filt.filter(stale) is False
    assert filt.filter(current) is True
    assert filt.filter(non_live) is True
