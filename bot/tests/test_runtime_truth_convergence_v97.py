from __future__ import annotations

import ast
import sys
import threading
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from bot import empty_position_sync_success_patch as empty_sync_patch
from bot import runtime_truth_convergence_v97_patch as patch


def test_canonical_fast_path_installs_v97_before_strategy_integrity() -> None:
    source = (Path(__file__).resolve().parents[1] / "bot.py").read_text(encoding="utf-8")
    module = ast.parse(source)
    installers = None
    for node in module.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "_FAST_PATH_INSTALLERS":
                    installers = list(ast.literal_eval(node.value))
    assert installers is not None
    modules = [name for name, _label in installers]
    assert modules.index("bot.trading_strategy_apex_wiring_patch") < modules.index(
        "bot.runtime_truth_convergence_v97_patch"
    ) < modules.index("bot.strategy_runtime_integrity_patch")


def test_apex_recovery_loads_class_from_source_when_partial_module_has_no_class(tmp_path, monkeypatch) -> None:
    source = tmp_path / "nija_apex_strategy_v71.py"
    source.write_text("class NIJAApexStrategyV71:\n    pass\n", encoding="utf-8")
    wiring = ModuleType("test_wiring")
    wiring.__file__ = str(tmp_path / "trading_strategy_apex_wiring_patch.py")

    partial = ModuleType("bot.nija_apex_strategy_v71")
    partial.__file__ = str(source)
    monkeypatch.setitem(sys.modules, "bot.nija_apex_strategy_v71", partial)
    monkeypatch.delitem(sys.modules, "nija_apex_strategy_v71", raising=False)
    monkeypatch.delitem(sys.modules, patch._RECOVERY_MODULE, raising=False)
    monkeypatch.setattr(patch, "_RECOVERED_APEX_CLASS", None)

    cls, recovered_from = patch._recover_apex_class_from_source(wiring)

    assert cls is not None
    assert cls.__name__ == "NIJAApexStrategyV71"
    assert recovered_from == patch._RECOVERY_MODULE
    assert getattr(partial, "NIJAApexStrategyV71") is cls


def test_partial_apex_preempts_recursive_legacy_resolver_on_source_loaded_alias(tmp_path, monkeypatch) -> None:
    source = tmp_path / "nija_apex_strategy_v71.py"
    source.write_text("class NIJAApexStrategyV71:\n    pass\n", encoding="utf-8")

    calls: list[str] = []
    wiring = ModuleType("nija_trading_strategy_apex_wiring_patch")
    wiring.__file__ = str(tmp_path / "trading_strategy_apex_wiring_patch.py")

    def recursive_legacy_resolver():
        calls.append("legacy")
        raise RecursionError("flat alias loop")

    wiring._resolve_apex_class = recursive_legacy_resolver
    partial = ModuleType("bot.nija_apex_strategy_v71")
    partial.__file__ = str(source)

    monkeypatch.setitem(sys.modules, "nija_trading_strategy_apex_wiring_patch", wiring)
    monkeypatch.setitem(sys.modules, "bot.nija_apex_strategy_v71", partial)
    monkeypatch.delitem(sys.modules, "nija_apex_strategy_v71", raising=False)
    monkeypatch.delitem(sys.modules, patch._RECOVERY_MODULE, raising=False)
    monkeypatch.setattr(patch, "_RECOVERED_APEX_CLASS", None)

    assert patch._patch_apex_wiring(wiring)
    cls, recovered_from = wiring._resolve_apex_class()

    assert cls is not None
    assert cls.__name__ == "NIJAApexStrategyV71"
    assert recovered_from == patch._RECOVERY_MODULE
    assert calls == []
    assert getattr(partial, "NIJAApexStrategyV71") is cls


def test_patch_loaded_discovers_source_loaded_wiring_alias_by_file(tmp_path, monkeypatch) -> None:
    source = tmp_path / "nija_apex_strategy_v71.py"
    source.write_text("class NIJAApexStrategyV71:\n    pass\n", encoding="utf-8")

    wiring = ModuleType("runtime_alias_which_does_not_match_canonical_name")
    wiring.__file__ = str(tmp_path / "trading_strategy_apex_wiring_patch.py")
    wiring._resolve_apex_class = lambda: (None, "legacy_missing")
    partial = ModuleType("bot.nija_apex_strategy_v71")
    partial.__file__ = str(source)

    monkeypatch.setitem(sys.modules, wiring.__name__, wiring)
    monkeypatch.setitem(sys.modules, "bot.nija_apex_strategy_v71", partial)
    monkeypatch.delitem(sys.modules, patch._RECOVERY_MODULE, raising=False)
    monkeypatch.setattr(patch, "_RECOVERED_APEX_CLASS", None)

    patch._patch_loaded()

    assert getattr(wiring._resolve_apex_class, patch._APEX_ATTR, False) is True
    cls, _source = wiring._resolve_apex_class()
    assert cls is not None
    assert cls.__name__ == "NIJAApexStrategyV71"


def test_position_fetch_failure_revokes_previous_sync_success(monkeypatch) -> None:
    class KrakenBroker:
        def __init__(self) -> None:
            self._startup_position_sync_adopted = True

        def get_positions(self):
            raise TimeoutError("slow exchange")

    module = ModuleType("test_broker_manager")
    module.KrakenBroker = KrakenBroker
    assert patch._patch_position_broker_module(module)

    broker = KrakenBroker()
    monkeypatch.setenv("NIJA_POSITION_SYNC_ACTIVATION_READY", "1")
    monkeypatch.setenv("NIJA_POSITION_SYNC_DISPATCH_READY", "1")

    with pytest.raises(TimeoutError):
        broker.get_positions()

    assert broker._startup_position_sync_adopted is False
    assert broker._startup_position_sync_fetch_ok is False
    assert "TimeoutError" in broker._startup_position_sync_error
    assert patch.os.environ["NIJA_POSITION_SYNC_ACTIVATION_READY"] == "0"
    assert patch.os.environ["NIJA_POSITION_SYNC_DISPATCH_READY"] == "0"


def test_position_refresh_keeps_prior_fetch_proof_visible_until_success(monkeypatch) -> None:
    started = threading.Event()
    release = threading.Event()

    class CoinbaseBroker:
        def __init__(self) -> None:
            self._startup_position_sync_adopted = True
            self._startup_position_sync_fetch_ok = True
            self._startup_position_sync_error = None

    def raw_get_positions(self):
        started.set()
        assert release.wait(2)
        return []

    wrapped = patch._wrap_position_fetch(raw_get_positions, "coinbase")
    broker = CoinbaseBroker()
    result: list[object] = []

    worker = threading.Thread(target=lambda: result.append(wrapped(broker)))
    worker.start()
    assert started.wait(1)

    # v426 invariant: a replacement read does not erase the last current proof
    # merely because I/O is still running.
    assert broker._startup_position_sync_fetch_ok is True

    release.set()
    worker.join(2)
    assert not worker.is_alive()
    assert result == [[]]
    assert broker._startup_position_sync_fetch_ok is True
    assert patch._fetch_attempt_seq(broker) == 1


def test_position_refresh_completed_failure_revokes_prior_fetch_proof(monkeypatch) -> None:
    class CoinbaseBroker:
        def __init__(self) -> None:
            self._startup_position_sync_adopted = True
            self._startup_position_sync_fetch_ok = True
            self._startup_position_sync_error = None

    def raw_get_positions(self):
        raise TimeoutError("completed exchange failure")

    wrapped = patch._wrap_position_fetch(raw_get_positions, "coinbase")
    broker = CoinbaseBroker()
    monkeypatch.setenv("NIJA_POSITION_SYNC_ACTIVATION_READY", "1")
    monkeypatch.setenv("NIJA_POSITION_SYNC_DISPATCH_READY", "1")

    with pytest.raises(TimeoutError, match="completed exchange failure"):
        wrapped(broker)

    assert broker._startup_position_sync_fetch_ok is False
    assert broker._startup_position_sync_adopted is False
    assert "TimeoutError" in broker._startup_position_sync_error
    assert patch.os.environ["NIJA_POSITION_SYNC_ACTIVATION_READY"] == "0"
    assert patch.os.environ["NIJA_POSITION_SYNC_DISPATCH_READY"] == "0"


def test_startup_refresh_preserves_prior_proof_until_authoritative_generation_advances() -> None:
    observed: list[object] = []

    class Broker:
        _startup_position_sync_adopted = True
        _startup_position_sync_fetch_ok = True
        _startup_position_sync_error = None
        _nija_authoritative_position_snapshot_generation_v285 = 7

    def canonical_adopt(broker, broker_name, eps):
        del broker_name, eps
        observed.append(broker._startup_position_sync_fetch_ok)
        broker._nija_authoritative_position_snapshot_generation_v285 += 1
        broker._startup_position_sync_adopted = True
        broker._startup_position_sync_fetch_ok = True
        broker._startup_position_sync_error = None
        return 0

    module = ModuleType("bot.startup_position_sync")
    module._adopt_broker_positions = canonical_adopt
    assert patch._patch_startup_sync_module(module)

    broker = Broker()
    assert module._adopt_broker_positions(broker, "platform:coinbase", None) == 0
    assert observed == [True]
    assert broker._startup_position_sync_fetch_ok is True
    assert broker._nija_authoritative_position_snapshot_generation_v285 == 8


def test_startup_refresh_accepts_exact_completed_v98_proxy_observation() -> None:
    class Broker:
        _startup_position_sync_adopted = True
        _startup_position_sync_fetch_ok = True
        _startup_position_sync_error = None
        _nija_authoritative_position_snapshot_generation_v285 = 7

    class _FetchProofProxy:
        __slots__ = ("_broker", "fetch_attempted", "fetch_ok")

        def __init__(self, broker) -> None:
            object.__setattr__(self, "_broker", broker)
            object.__setattr__(self, "fetch_attempted", False)
            object.__setattr__(self, "fetch_ok", None)

        def __getattr__(self, name):
            return getattr(object.__getattribute__(self, "_broker"), name)

        def __setattr__(self, name, value):
            if name in {"_broker", "fetch_attempted", "fetch_ok"}:
                object.__setattr__(self, name, value)
                return
            setattr(object.__getattribute__(self, "_broker"), name, value)

    real = Broker()
    proxy = _FetchProofProxy(real)

    def canonical_adopt(broker, broker_name, eps):
        del broker_name, eps
        # Reproduce the v98 outer wrapper contract: v97 sees no generation or
        # attempt-sequence edge on the real object, but the exact v98 observer
        # has proof that get_positions completed successfully.
        broker.fetch_attempted = True
        broker.fetch_ok = True
        broker._startup_position_sync_adopted = True
        broker._startup_position_sync_fetch_ok = True
        broker._startup_position_sync_error = None
        return 0

    module = ModuleType("bot.startup_position_sync")
    module._adopt_broker_positions = canonical_adopt
    assert patch._patch_startup_sync_module(module)

    assert module._adopt_broker_positions(proxy, "user:test:kraken", None) == 0
    assert real._startup_position_sync_fetch_ok is True
    assert patch._completed_v98_proxy_fetch(proxy) is True


def test_startup_refresh_without_observable_replacement_proof_returns_to_unknown() -> None:
    class Broker:
        _startup_position_sync_adopted = True
        _startup_position_sync_fetch_ok = True
        _startup_position_sync_error = None
        _nija_authoritative_position_snapshot_generation_v285 = 7

    def canonical_adopt(broker, broker_name, eps):
        del broker, broker_name, eps
        return 0

    module = ModuleType("bot.startup_position_sync")
    module._adopt_broker_positions = canonical_adopt
    assert patch._patch_startup_sync_module(module)

    broker = Broker()
    assert module._adopt_broker_positions(broker, "platform:coinbase", None) == 0
    assert broker._startup_position_sync_fetch_ok is None


def test_nested_position_wrapper_preserves_failure_masked_as_empty(monkeypatch) -> None:
    class KrakenBroker:
        def __init__(self) -> None:
            self._startup_position_sync_adopted = True

    def raw_get_positions(self):
        raise TimeoutError("slow exchange")

    inner = patch._wrap_position_fetch(raw_get_positions, "kraken")

    def compatibility_equity_wrapper(self):
        try:
            return inner(self)
        except TimeoutError:
            return []

    outer = patch._wrap_position_fetch(compatibility_equity_wrapper, "kraken")
    broker = KrakenBroker()
    monkeypatch.setenv("NIJA_POSITION_SYNC_ACTIVATION_READY", "1")
    monkeypatch.setenv("NIJA_POSITION_SYNC_DISPATCH_READY", "1")

    assert outer(broker) == []
    assert broker._startup_position_sync_fetch_ok is False
    assert broker._startup_position_sync_adopted is False
    assert "TimeoutError" in broker._startup_position_sync_error
    assert patch.os.environ["NIJA_POSITION_SYNC_ACTIVATION_READY"] == "0"
    assert patch.os.environ["NIJA_POSITION_SYNC_DISPATCH_READY"] == "0"


def test_startup_sync_guard_rejects_masked_empty_success(monkeypatch) -> None:
    class Broker:
        _startup_position_sync_adopted = False
        _startup_position_sync_fetch_ok = None
        _startup_position_sync_error = None

    def canonical_adopt(broker, broker_name, eps):
        broker._startup_position_sync_fetch_ok = False
        broker._startup_position_sync_error = "TimeoutError:slow exchange"
        broker._startup_position_sync_adopted = True
        return 0

    module = ModuleType("bot.startup_position_sync")
    module._adopt_broker_positions = canonical_adopt
    assert patch._patch_startup_sync_module(module)

    broker = Broker()
    monkeypatch.setenv("NIJA_POSITION_SYNC_ACTIVATION_READY", "1")
    monkeypatch.setenv("NIJA_POSITION_SYNC_DISPATCH_READY", "1")
    assert module._adopt_broker_positions(broker, "platform:kraken", None) == 0

    assert broker._startup_position_sync_adopted is False
    assert broker._startup_position_sync_fetch_ok is False
    assert patch.os.environ["NIJA_POSITION_SYNC_ACTIVATION_READY"] == "0"
    assert patch.os.environ["NIJA_POSITION_SYNC_DISPATCH_READY"] == "0"


def test_empty_sync_compatibility_wrapper_never_refetches_broker() -> None:
    calls: list[str] = []

    class Broker:
        connected = True
        _startup_position_sync_adopted = False
        _startup_position_sync_fetch_ok = True

        def get_positions(self):
            raise AssertionError("compatibility wrapper must not refetch")

    def canonical_adopt(broker, broker_name, eps):
        calls.append(broker_name)
        broker._startup_position_sync_adopted = True
        return 0

    module = ModuleType("bot.startup_position_sync")
    module._adopt_broker_positions = canonical_adopt
    assert empty_sync_patch._patch(module)

    broker = Broker()
    assert module._adopt_broker_positions(broker, "platform:kraken", None) == 0
    assert calls == ["platform:kraken"]
    assert broker._startup_position_sync_adopted is True


def test_empty_sync_compatibility_wrapper_preserves_failure_proof() -> None:
    class Broker:
        connected = True
        _startup_position_sync_adopted = False
        _startup_position_sync_fetch_ok = False
        _startup_position_sync_error = "TimeoutError:slow exchange"

    def canonical_adopt(broker, broker_name, eps):
        broker._startup_position_sync_adopted = True
        return 0

    module = ModuleType("bot.startup_position_sync")
    module._adopt_broker_positions = canonical_adopt
    assert empty_sync_patch._patch(module)

    broker = Broker()
    assert module._adopt_broker_positions(broker, "platform:kraken", None) == 0
    assert broker._startup_position_sync_adopted is False


def test_scan_phase_records_writer_lifecycle(monkeypatch) -> None:
    events: list[str] = []
    runtime = SimpleNamespace(
        record_scan_started=lambda: events.append("started"),
        record_scan_complete=lambda: events.append("complete"),
    )
    writer = ModuleType("bot.entrypoint_writer_authority")
    writer.get_entrypoint_writer_authority = lambda: runtime
    monkeypatch.setitem(sys.modules, "bot.entrypoint_writer_authority", writer)

    class NijaCoreLoop:
        def run_scan_phase(self):
            events.append("scan")
            return "ok"

    core = ModuleType("bot.nija_core_loop")
    core.NijaCoreLoop = NijaCoreLoop
    assert patch._patch_core_loop(core)

    assert NijaCoreLoop().run_scan_phase() == "ok"
    assert events == ["started", "scan", "complete"]
