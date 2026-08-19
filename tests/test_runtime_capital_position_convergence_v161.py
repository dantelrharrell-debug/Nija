from __future__ import annotations

import queue
import threading
import time
from types import SimpleNamespace

import bot.runtime_capital_position_convergence_v161_patch as v161


class _AliveThread:
    def is_alive(self) -> bool:
        return True


class _Broker:
    def __init__(self, balance: float = 100.0, age_s: float = 5.0):
        self.connected = True
        self._last_known_balance = balance
        self._balance_last_updated = time.time() - age_s
        self._startup_position_sync_adopted = False
        self._startup_position_sync_fetch_ok = None
        self._startup_position_sync_error = None


def test_stale_flight_threshold_stays_inside_fetch_budget(monkeypatch):
    guard = SimpleNamespace(_broker_timeout_seconds=lambda broker_id: 75.0)
    monkeypatch.setattr(v161, "_guard_module", lambda: guard)
    monkeypatch.setattr(v161, "_fetch_budget_seconds", lambda: 50.0)
    monkeypatch.delenv("NIJA_CAPITAL_STALE_FLIGHT_AFTER_S", raising=False)

    assert v161._stale_flight_after_seconds("kraken") == 45.0


def test_fresh_broker_owned_balance_seeds_guard_but_stale_does_not(monkeypatch):
    observations = {}
    lock = threading.Lock()

    class Observation:
        def __init__(self, value, observed_monotonic, observed_epoch, sequence):
            self.value = value
            self.observed_monotonic = observed_monotonic
            self.observed_epoch = observed_epoch
            self.sequence = sequence

    guard = SimpleNamespace(
        _coerce_scalar=lambda value: float(value),
        _freshness_ttl_seconds=lambda: 90.0,
        _OBSERVATIONS=observations,
        _OBSERVATION_LOCK=lock,
        _BROKER_SEQUENCE={"kraken": 7},
        _Observation=Observation,
    )

    fresh = _Broker(242.0, age_s=10.0)
    assert v161._seed_fresh_broker_observation(guard, "kraken", fresh) is True
    assert observations["kraken"].value == 242.0
    assert observations["kraken"].sequence == 7

    observations.clear()
    stale = _Broker(242.0, age_s=120.0)
    assert v161._seed_fresh_broker_observation(guard, "kraken", stale) is False
    assert observations == {}


def test_stale_balance_flight_is_rotated_and_orphan_count_is_bounded(monkeypatch):
    flight = SimpleNamespace(
        thread=_AliveThread(),
        result_queue=queue.Queue(maxsize=1),
        sequence=3,
        started_monotonic=time.monotonic() - 60.0,
        timeout_s=75.0,
    )
    guard = SimpleNamespace(
        _IN_FLIGHT={"kraken": flight},
        _IN_FLIGHT_LOCK=threading.Lock(),
    )
    monkeypatch.setattr(v161, "_stale_flight_after_seconds", lambda broker_id: 45.0)
    monkeypatch.setattr(v161, "_max_orphaned_flights", lambda: 2)
    v161._ORPHANED_FLIGHTS.clear()

    v161._supersede_stale_guard_flights(guard, {"kraken": object()})

    assert "kraken" not in guard._IN_FLIGHT
    assert v161._ORPHANED_FLIGHTS["kraken"] == [flight]

    # With two still-alive orphans, the current request is retained rather than
    # spawning an unbounded third abandoned worker.
    second = SimpleNamespace(thread=_AliveThread())
    v161._ORPHANED_FLIGHTS["kraken"] = [flight, second]
    current = SimpleNamespace(
        thread=_AliveThread(),
        sequence=4,
        started_monotonic=time.monotonic() - 60.0,
        timeout_s=75.0,
    )
    guard._IN_FLIGHT["kraken"] = current
    v161._supersede_stale_guard_flights(guard, {"kraken": object()})
    assert guard._IN_FLIGHT["kraken"] is current


def test_position_worker_retries_timeout_and_only_becomes_ready_after_real_success(monkeypatch):
    broker = _Broker()
    calls = []
    readiness = []
    active = set()
    key = (11, 22)
    active.add(key)

    def adopt(broker_arg, broker_name, eps):
        calls.append(broker_name)
        if len(calls) < 3:
            raise TimeoutError("slow position snapshot")
        broker_arg._startup_position_sync_adopted = True
        broker_arg._startup_position_sync_fetch_ok = True
        broker_arg._startup_position_sync_error = None
        return 0

    sync_module = SimpleNamespace(
        _get_entry_price_store=lambda: None,
        _adopt_broker_positions=adopt,
    )
    fake_v108 = SimpleNamespace(
        _retry_policy=lambda: (4, 0.01, 0.01),
        _publish_readiness=lambda manager, source: readiness.append(
            (source, broker._startup_position_sync_adopted)
        ),
        _LOCK=threading.RLock(),
        _ACTIVE=active,
    )
    monkeypatch.setattr(v161, "_startup_sync_module", lambda: sync_module)
    monkeypatch.setattr(v161.time, "sleep", lambda delay: None)

    v161._position_worker_v161(fake_v108, object(), "kraken", broker, key, "test")

    assert calls == ["platform:kraken"] * 3
    assert readiness[0][1] is False
    assert readiness[1][1] is False
    assert readiness[2][1] is True
    assert readiness[-1][1] is True
    assert broker._startup_position_sync_adopted is True
    assert key not in active


def test_monitor_dispatches_position_sync_independent_of_capital_refresh(monkeypatch):
    manager = object()
    events = []
    fake_v108 = SimpleNamespace(
        dispatch_platform_position_sync=lambda mgr, trigger: events.append(("dispatch", trigger)) or 1,
        _publish_readiness=lambda mgr, source: events.append(("publish", source)),
    )
    monkeypatch.setattr(v161, "_canonical_manager", lambda: manager)
    monkeypatch.setattr(v161, "_v108_module", lambda: fake_v108)

    started, published = v161._position_monitor_iteration()

    assert started == 1
    assert published is True
    assert events == [
        ("dispatch", "v161_monitor"),
        ("publish", "v161_monitor_tick"),
    ]


def test_release_manifest_attests_v161(monkeypatch):
    required = {}
    fake_manifest = SimpleNamespace(_REQUIRED_FLAGS=required)
    real_import = v161.importlib.import_module

    def fake_import(name):
        if name == "bot.runtime_release_manifest_patch":
            return fake_manifest
        return real_import(name)

    monkeypatch.setattr(v161.importlib, "import_module", fake_import)
    assert v161._patch_release_manifest() is True
    assert required["runtime_capital_position_convergence_v161"] == v161._READY_FLAG
