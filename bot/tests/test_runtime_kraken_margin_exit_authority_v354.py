from __future__ import annotations

import importlib


v354 = importlib.import_module("bot.runtime_kraken_margin_exit_authority_v354_patch")
submitter = importlib.import_module("bot.pipeline_order_submitter")


def _install_over(fake):
    prior = submitter._resolve_margin_exit
    submitter._resolve_margin_exit = fake
    try:
        assert v354._patch_submitter() is True
        return prior, submitter._resolve_margin_exit
    except Exception:
        submitter._resolve_margin_exit = prior
        raise


def test_pending_open_cannot_authorize_margin_exit_transform():
    def fake(preferred_broker, account_id, symbol):
        return {
            "leverage": 2,
            "margin_mode": "cross",
            "reduce_only": True,
            "intent_type": "exit",
            "reason": "existing_margin_position:pending_open",
        }

    prior, patched = _install_over(fake)
    try:
        assert patched("kraken", "platform", "XETHZUSD") == {}
    finally:
        submitter._resolve_margin_exit = prior


def test_confirmed_open_margin_position_remains_authoritative():
    expected = {
        "leverage": 2,
        "margin_mode": "cross",
        "reduce_only": True,
        "intent_type": "exit",
        "reason": "existing_margin_position:open",
    }

    def fake(preferred_broker, account_id, symbol):
        return dict(expected)

    prior, patched = _install_over(fake)
    try:
        assert patched("kraken", "platform", "XETHZUSD") == expected
    finally:
        submitter._resolve_margin_exit = prior


def test_reducing_margin_position_remains_authoritative():
    expected = {
        "leverage": 3,
        "margin_mode": "cross",
        "reduce_only": True,
        "intent_type": "exit",
        "reason": "existing_margin_position:reducing",
    }

    def fake(preferred_broker, account_id, symbol):
        return dict(expected)

    prior, patched = _install_over(fake)
    try:
        assert patched("kraken", "platform", "XETHZUSD") == expected
    finally:
        submitter._resolve_margin_exit = prior
