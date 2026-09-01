from __future__ import annotations


def test_trusted_close_requires_full_canonical_exit_contract():
    from bot import runtime_exit_capability_semantics_v335_patch as v335

    good = {
        "intent_type": "exit",
        "position_effect": "close",
        "metadata_override": {
            "closing_position": True,
            "protective_exit": True,
            "exit_origin": "universal_v67",
        },
    }
    assert v335._trusted_exit_kwargs(good) is True

    missing_origin = dict(good)
    missing_origin["metadata_override"] = dict(good["metadata_override"])
    missing_origin["metadata_override"].pop("exit_origin")
    assert v335._trusted_exit_kwargs(missing_origin) is False

    spoof_entry = dict(good)
    spoof_entry["intent_type"] = "entry"
    assert v335._trusted_exit_kwargs(spoof_entry) is False


def test_sell_to_close_can_neutralize_only_short_classification(monkeypatch):
    from bot import exchange_capabilities
    from bot import runtime_exit_capability_semantics_v335_patch as v335

    original = exchange_capabilities.ExchangeCapabilityMatrix.enforce_order_capabilities
    assert v335._patch_capability_matrix() is True
    matrix = exchange_capabilities.ExchangeCapabilityMatrix()

    # Ordinary Kraken spot SELL remains a blocked short outside trusted close scope.
    allowed, reason = matrix.enforce_order_capabilities(
        broker="kraken",
        symbol="ETH-USD",
        side="sell",
        leverage=1.0,
        margin_mode="spot",
        runtime_overrides={},
    )
    assert allowed is False
    assert reason.startswith("short_not_supported")

    token = v335._TRUSTED_CLOSE.set(True)
    try:
        allowed, reason = matrix.enforce_order_capabilities(
            broker="kraken",
            symbol="ETH-USD",
            side="sell",
            leverage=1.0,
            margin_mode="spot",
            runtime_overrides={},
        )
    finally:
        v335._TRUSTED_CLOSE.reset(token)

    assert allowed is True
    assert reason == "ok"
    # Global exchange capability is still unchanged: Kraken spot cannot open shorts.
    assert exchange_capabilities.can_short("kraken", "ETH-USD") is False

    monkeypatch.setattr(
        exchange_capabilities.ExchangeCapabilityMatrix,
        "enforce_order_capabilities",
        original,
    )


def test_untrusted_sell_stays_blocked_even_if_other_exit_words_present():
    from bot import runtime_exit_capability_semantics_v335_patch as v335

    assert v335._trusted_exit_kwargs({
        "intent_type": "exit",
        "position_effect": "close",
        "metadata_override": {
            "closing_position": True,
            "protective_exit": True,
            "exit_origin": "unknown_caller",
        },
    }) is False
