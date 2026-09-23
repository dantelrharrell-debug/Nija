from __future__ import annotations

from functools import wraps
from types import SimpleNamespace

import bot.capital_publication_liveness_v142_patch as v142


def test_reassert_uses_wrapper_markers_without_rewrapping(monkeypatch):
    calls = {"v35": 0, "v78": 0}

    def base_pipeline(self, broker_map, trigger, open_exposure_usd):
        return None

    @wraps(base_pipeline)
    def bounded_pipeline(self, broker_map, trigger, open_exposure_usd):
        return base_pipeline(self, broker_map, trigger, open_exposure_usd)

    # functools.wraps preserves the original display name.  The safety marker,
    # not __name__, is the stable ownership proof.
    bounded_pipeline._nija_capital_refresh_stall_guard_v36 = True

    class Coordinator:
        _pipeline = bounded_pipeline

    class Batch:
        def __init__(self, broker_map):
            self.broker_map = broker_map

    original_init = Batch.__init__

    @wraps(original_init)
    def bounded_init(self, broker_map):
        original_init(self, broker_map)

    v78_marker = "_nija_capital_refresh_live_continuity_v78"
    setattr(bounded_init, v78_marker, True)
    Batch.__init__ = bounded_init

    flow = SimpleNamespace(CapitalRefreshCoordinator=Coordinator)

    def v35_patch(_flow):
        calls["v35"] += 1
        return True

    def v78_patch(_guard):
        calls["v78"] += 1
        return True

    v35 = SimpleNamespace(_BalanceFetchBatch=Batch, _patch=v35_patch)
    v78 = SimpleNamespace(_PATCH_ATTR=v78_marker, _patch_guard=v78_patch)

    real_import = v142.importlib.import_module

    def fake_import(name, package=None):
        if name in {"bot.capital_flow_state_machine", "capital_flow_state_machine"}:
            return flow
        if name == "bot.capital_refresh_stall_guard_v35":
            return v35
        if name == "bot.capital_refresh_live_continuity_v78_patch":
            return v78
        return real_import(name, package)

    monkeypatch.setattr(v142.importlib, "import_module", fake_import)

    before_pipeline = Coordinator._pipeline
    before_init = Batch.__init__

    ok, detail = v142._reassert_bounded_fetch_contract()

    assert ok is True
    assert detail == "v35_v36_and_v78_proven"
    assert calls == {"v35": 0, "v78": 0}
    assert Coordinator._pipeline is before_pipeline
    assert Batch.__init__ is before_init

    # These copied names are exactly why name-based ownership checks are unsafe.
    assert Coordinator._pipeline.__name__ == "base_pipeline"
    assert Batch.__init__.__name__ == "__init__"
