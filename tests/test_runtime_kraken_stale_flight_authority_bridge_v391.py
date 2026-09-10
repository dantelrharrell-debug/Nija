from collections import namedtuple
from datetime import datetime, timezone
from types import SimpleNamespace

import bot.runtime_kraken_stale_flight_authority_bridge_v391_patch as v391


Observation = namedtuple("Observation", "value observed_monotonic observed_epoch sequence")


def test_authority_observation_requires_fresh_timestamp(monkeypatch):
    now = datetime.now(timezone.utc)
    authority = SimpleNamespace(
        _lock=None,
        _broker_balances={"kraken": 149.85},
        _broker_feed_timestamps={"kraken": now},
    )
    capital_module = SimpleNamespace(get_capital_authority=lambda: authority)
    real_import = v391.importlib.import_module

    def fake_import(name):
        if name == "bot.capital_authority":
            return capital_module
        return real_import(name)

    monkeypatch.setattr(v391.importlib, "import_module", fake_import)
    guard = SimpleNamespace(
        _coerce_scalar=lambda value: float(value),
        _freshness_ttl_seconds=lambda: 90.0,
        _OBSERVATIONS={},
        _Observation=Observation,
        _OBSERVATION_LOCK=None,
        _BROKER_SEQUENCE={"kraken": 7},
    )

    assert v391._authority_observation(guard, "kraken") is True
    obs = guard._OBSERVATIONS["kraken"]
    assert obs.value == 149.85
    assert obs.sequence == 7
    assert obs.observed_epoch > 0
