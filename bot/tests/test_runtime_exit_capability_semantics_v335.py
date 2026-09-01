from __future__ import annotations

import importlib


def test_trusted_exit_requires_full_canonical_metadata():
    v335 = importlib.import_module("bot.runtime_exit_capability_semantics_v335_patch")
    assert v335._trusted_exit_kwargs({
        "intent_type": "exit",
        "position_effect": "close",
        "metadata_override": {
            "protective_exit": True,
            "closing_position": True,
            "exit_origin": "universal_v67",
        },
    }) is True
    assert v335._trusted_exit_kwargs({
        "intent_type": "exit",
        "position_effect": "close",
        "metadata_override": {"protective_exit": True},
    }) is False
    assert v335._trusted_exit_kwargs({
        "intent_type": "entry",
        "position_effect": "close",
        "metadata_override": {
            "protective_exit": True,
            "closing_position": True,
            "exit_origin": "universal_v67",
        },
    }) is False


def test_ordinary_kraken_spot_sell_remains_short_blocked():
    caps = importlib.import_module("bot.exchange_capabilities")
    allowed, reason = caps.EXCHANGE_CAPABILITIES.enforce_order_capabilities(
        broker="kraken", symbol="ETH-USD", side="sell"
    )
    assert allowed is False
    assert reason == "short_not_supported:kraken:spot"


def test_trusted_close_only_neutralizes_short_entry_classification(monkeypatch):
    v335 = importlib.import_module("bot.runtime_exit_capability_semantics_v335_patch")
    caps = importlib.import_module("bot.exchange_capabilities")
    assert v335._patch_capability_matrix() is True

    # Without the context token, the normal spot-short prohibition is intact.
    allowed, reason = caps.EXCHANGE_CAPABILITIES.enforce_order_capabilities(
        broker="kraken", symbol="ETH-USD", side="sell"
    )
    assert allowed is False
    assert reason == "short_not_supported:kraken:spot"

    token = v335._TRUSTED_CLOSE.set(True)
    try:
        allowed, reason = caps.EXCHANGE_CAPABILITIES.enforce_order_capabilities(
            broker="kraken", symbol="ETH-USD", side="sell"
        )
    finally:
        v335._TRUSTED_CLOSE.reset(token)
    assert allowed is True
    assert reason == "ok"


def test_trusted_close_does_not_bypass_other_capability_checks():
    v335 = importlib.import_module("bot.runtime_exit_capability_semantics_v335_patch")
    caps = importlib.import_module("bot.exchange_capabilities")
    assert v335._patch_capability_matrix() is True
    token = v335._TRUSTED_CLOSE.set(True)
    try:
        allowed, reason = caps.EXCHANGE_CAPABILITIES.enforce_order_capabilities(
            broker="kraken",
            symbol="ETH-USD",
            side="sell",
            leverage=2.0,
        )
    finally:
        v335._TRUSTED_CLOSE.reset(token)
    assert allowed is False
    assert reason.startswith("leverage_not_supported:")
