from __future__ import annotations

import importlib


class Broker:
    def __init__(self, connected):
        self.connected = connected


class BrokerProxy:
    def __init__(self, broker, connected=None):
        self._broker = broker
        if connected is not None:
            self.connected = connected


def test_exact_broker_health_requires_positive_local_state():
    v339 = importlib.import_module("bot.runtime_protective_exit_broker_health_v339_patch")
    ok, reason = v339._exact_broker_health(Broker(True))
    assert ok is True
    assert reason == "broker_local:connected"

    ok, reason = v339._exact_broker_health(Broker(False))
    assert ok is False
    assert reason == "broker_local:connected=false"


def test_exact_broker_health_uses_concrete_broker_behind_known_proxy():
    v339 = importlib.import_module("bot.runtime_protective_exit_broker_health_v339_patch")

    # A stale proxy false must not veto a healthy concrete adapter.
    ok, reason = v339._exact_broker_health(BrokerProxy(Broker(True), connected=False))
    assert ok is True
    assert reason == "broker_proxy:_broker->broker_local:connected"

    # A stale proxy true must not promote an unhealthy concrete adapter.
    ok, reason = v339._exact_broker_health(BrokerProxy(Broker(False), connected=True))
    assert ok is False
    assert reason == "broker_proxy:_broker->broker_local:connected=false"


def test_exact_broker_health_fails_closed_on_proxy_cycle():
    v339 = importlib.import_module("bot.runtime_protective_exit_broker_health_v339_patch")
    left = BrokerProxy(None)
    right = BrokerProxy(left)
    left._broker = right

    ok, reason = v339._exact_broker_health(left)
    assert ok is False
    assert reason == "broker_proxy_cycle"


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
