from __future__ import annotations

from bot.runtime_coinbase_exit_recovery_v344_patch import (
    _complete_coinbase_increment,
    _deterministic_non_health,
    _provenance_is_exactly_recoverable,
)


def test_v344_adds_btc_increment_only_when_coinbase_metadata_missing():
    result = _complete_coinbase_increment("BTC-USD", {})
    assert result["base_increment"] == 0.00000001


def test_v344_adds_eth_increment_when_metadata_is_none():
    result = _complete_coinbase_increment("ETH-USD", None)
    assert result["base_increment"] == 0.000001


def test_v344_preserves_real_coinbase_increment():
    original = {"base_increment": "0.00001", "base_min_size": "0.0001"}
    result = _complete_coinbase_increment("ETH-USD", original)
    assert result is original
    assert result["base_increment"] == "0.00001"


def test_v344_does_not_invent_increment_for_unlisted_asset():
    original = {"base_increment": None}
    result = _complete_coinbase_increment("SOME-USD", original)
    assert result is original
    assert result["base_increment"] is None


def test_v344_classifies_exact_internal_typeerror_as_non_exchange_health():
    assert _deterministic_non_health(
        "TypeError: '<=' not supported between instances of 'NoneType' and 'int'"
    )


def test_v344_classifies_v341_mismatch_as_non_exchange_health():
    assert _deterministic_non_health(
        "V341 base_notional_mismatch verified=3.0 price=1.2 expected=3.6 pipeline_notional=6.0"
    )


def test_v344_classifies_kraken_min_volume_as_feasibility_not_exchange_health():
    assert _deterministic_non_health("EGeneral:Invalid arguments:volume minimum not met")


def test_v344_does_not_classify_unknown_broker_rejection_as_safe():
    assert not _deterministic_non_health("EOrder:Insufficient funds")
    assert not _deterministic_non_health("exchange unavailable")
    assert not _deterministic_non_health("invalid API key")


def _row(reason: str, *, accepted: bool = False, source: str = "execution_pipeline"):
    return {"accepted": accepted, "source": source, "reason": reason}


def test_v344_exact_polluted_five_sample_is_recoverable():
    rows = [
        _row("TypeError: '<=' not supported between instances of 'NoneType' and 'int'"),
        _row("TypeError: '<=' not supported between instances of 'NoneType' and 'int'"),
        _row("TypeError: '<=' not supported between instances of 'NoneType' and 'int'"),
        _row("EGeneral:Invalid arguments:volume minimum not met"),
        _row("TypeError: '<=' not supported between instances of 'NoneType' and 'int'"),
    ]
    ok, detail = _provenance_is_exactly_recoverable(rows)
    assert ok is True
    assert detail == "exact_deterministic_five_sample_pollution"


def test_v344_unknown_exchange_reject_blocks_latch_recovery():
    rows = [
        _row("TypeError: '<=' not supported between instances of 'NoneType' and 'int'"),
        _row("TypeError: '<=' not supported between instances of 'NoneType' and 'int'"),
        _row("EGeneral:Invalid arguments:volume minimum not met"),
        _row("exchange unavailable"),
        _row("TypeError: '<=' not supported between instances of 'NoneType' and 'int'"),
    ]
    ok, detail = _provenance_is_exactly_recoverable(rows)
    assert ok is False
    assert detail.startswith("unknown_or_genuine_exchange_reject")


def test_v344_direct_or_legacy_source_blocks_latch_recovery():
    rows = [
        _row("TypeError: '<=' not supported between instances of 'NoneType' and 'int'"),
        _row("TypeError: '<=' not supported between instances of 'NoneType' and 'int'"),
        _row("EGeneral:Invalid arguments:volume minimum not met", source="direct_or_legacy"),
        _row("TypeError: '<=' not supported between instances of 'NoneType' and 'int'"),
        _row("TypeError: '<=' not supported between instances of 'NoneType' and 'int'"),
    ]
    ok, detail = _provenance_is_exactly_recoverable(rows)
    assert ok is False
    assert detail.startswith("non_pipeline_source")
