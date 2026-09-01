from __future__ import annotations

import importlib


class Broker:
    def __init__(self, connected):
        self.connected = connected


def test_exact_broker_health_requires_positive_local_state():
    v339 = importlib.import_module("bot.runtime_protective_exit_broker_health_v339_patch")
    ok, reason = v339._exact_broker_health(Broker(True))
    assert ok is True
    assert reason == "broker_local:connected"

    ok, reason = v339._exact_broker_health(Broker(False))
    assert ok is False
    assert reason == "broker_local:connected=false"


def test_exact_broker_health_fails_closed_without_state():
    v339 = importlib.import_module("bot.runtime_protective_exit_broker_health_v339_patch")
    ok, reason = v339._exact_broker_health(object())
    assert ok is False
    assert reason == "exact_broker_health_unproven"


def test_trusted_kwargs_reuses_v335_full_contract():
    v339 = importlib.import_module("bot.runtime_protective_exit_broker_health_v339_patch")
    assert v339._trusted_kwargs({
        "intent_type": "exit",
        "position_effect": "close",
        "metadata_override": {
            "protective_exit": True,
            "closing_position": True,
            "exit_origin": "universal_v67",
        },
    }) is True
    assert v339._trusted_kwargs({
        "intent_type": "entry",
        "position_effect": "close",
        "metadata_override": {
            "protective_exit": True,
            "closing_position": True,
            "exit_origin": "universal_v67",
        },
    }) is False
