from __future__ import annotations

import importlib.util
import ast
import logging
import threading
from collections.abc import Mapping
from types import SimpleNamespace
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
PATCHER_PATH = ROOT / "scripts" / "apply_execution_proof_startup_isolation_v339.py"


def _load_patcher():
    spec = importlib.util.spec_from_file_location("nija_v339_patcher_test", PATCHER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_launcher_patch_routes_authority_marker_before_startup_guard():
    patcher = _load_patcher()
    source = (ROOT / "scripts" / "canonical_runtime_launcher_v26.py").read_text(
        encoding="utf-8"
    )
    patched = patcher.patch_launcher_text(source)

    main_at = patched.index("def main()")
    prepare_at = patched.index(
        "_prepare_execution_proof_startup_isolation_v339()", main_at
    )
    startup_at = patched.index("install_canonical_startup_guard()", main_at)
    assert prepare_at < startup_at
    assert 'os.environ["HEARTBEAT_MARKER_PATH"] = authority_path' in patched
    assert 'os.environ["NIJA_EXECUTION_MARKER_PATH"] = execution_path' in patched


def test_v169_patch_quarantines_only_authority_origin_execution_marker():
    patcher = _load_patcher()
    source = (ROOT / "bot" / "runtime_execution_capital_integrity_v169_patch.py").read_text(
        encoding="utf-8"
    )
    patched = patcher.patch_v169_text(source)

    assert "def _quarantine_authority_execution_marker()" in patched
    assert 'source not in {"heartbeat_authority_single_source", "authority_heartbeat"}' in patched
    assert 'kind not in {"", "authority_liveness"}' in patched
    assert 'os.environ["HEARTBEAT_MARKER_PATH"] = str(execution_path)' in patched
    assert "authority_execution_marker_path_collision" in patched


def test_v238_patch_requires_v169_and_explicit_execution_provenance():
    patcher = _load_patcher()
    source = (ROOT / "bot" / "runtime_heartbeat_marker_convergence_v238_patch.py").read_text(
        encoding="utf-8"
    )
    patched = patcher.patch_v238_text(source)

    assert "v169_provenance_guard_not_ready" in patched
    assert 'allowed_sources = {"heartbeat_trade", "canonical_confirmed_fill"}' in patched
    assert 'source not in allowed_sources' in patched
    assert 'kind != "execution_probe"' in patched
    assert "verified_v169_execution_probe:source=" in patched


def test_v238_patch_preserves_render_compatibility_token():
    patcher = _load_patcher()
    source = (ROOT / "bot" / "runtime_heartbeat_marker_convergence_v238_patch.py").read_text(
        encoding="utf-8"
    )
    patched = patcher.patch_v238_text(source)

    # render_entrypoint.sh still validates that the historical hardening token exists.
    assert 'source != "heartbeat_trade"' in patched


def test_v339_source_transformations_are_idempotent():
    patcher = _load_patcher()

    launcher = (ROOT / "scripts" / "canonical_runtime_launcher_v26.py").read_text(
        encoding="utf-8"
    )
    once = patcher.patch_launcher_text(launcher)
    assert patcher.patch_launcher_text(once) == once

    v169 = (ROOT / "bot" / "runtime_execution_capital_integrity_v169_patch.py").read_text(
        encoding="utf-8"
    )
    once = patcher.patch_v169_text(v169)
    assert patcher.patch_v169_text(once) == once

    v238 = (ROOT / "bot" / "runtime_heartbeat_marker_convergence_v238_patch.py").read_text(
        encoding="utf-8"
    )
    once = patcher.patch_v238_text(v238)
    assert patcher.patch_v238_text(once) == once

def test_v346_restart_recovery_preserves_authenticated_trade_time():
    patcher = _load_patcher()
    source = (ROOT / "bot" / "runtime_execution_position_readiness_v346_patch.py").read_text(
        encoding="utf-8"
    )
    patched = patcher.patch_v346_text(source)

    assert '"broker_fill_at_epoch": float(trade_ts)' in patched
    assert "must never make an older recovered fill fresh" in patched


def _recovery_namespace(*, fill, event_time=9990.0):
    patcher = _load_patcher()
    patched = patcher.patch_v346_text(
        (ROOT / "bot/runtime_execution_position_readiness_v346_patch.py").read_text()
    )
    function = next(n for n in ast.parse(patched).body
                    if isinstance(n, ast.FunctionDef) and n.name == "_recover_recent_kraken_execution_proof")
    captured = []
    calls = []

    def normalize(result, *, symbol, side):
        captured.append(dict(result))
        return result["filled_price"], result["filled_size_usd"]

    def private_read(broker, method, params):
        calls.append(method)
        return {"error": [], "result": {"trades": {
            "T": {"ordertxid": "ORDER", "type": "sell", "pair": "XXBTZUSD", "time": event_time}
        }}}

    modules = {
        "bot.runtime_kraken_delayed_fill_reconciliation_v357_patch": SimpleNamespace(
            _private_read=private_read,
            _query_order_row=lambda broker, oid: {"status": "closed"},
            _query_order_fill=lambda row: ("closed", 0.0, 0.0, 0.0),
            _trade_history_fill=lambda broker, **kwargs: fill,
        ),
        "bot.runtime_confirmed_fill_profitability_v328_patch": SimpleNamespace(_normalize_dict_fill=normalize),
    }
    ns = {
        "Mapping": Mapping, "Any": object, "MARKER": "test",
        "importlib": SimpleNamespace(import_module=lambda name: modules[name]),
        "LOGGER": logging.getLogger("test.execution_recovery"),
        "time": SimpleNamespace(time=lambda: 10000.0, monotonic=lambda: 10000.0),
        "_RECOVERY_LOCK": threading.RLock(), "_RECOVERY_LAST_ATTEMPT_MONO": 0.0,
        "_RECOVERY_LAST_GENERATION": "", "_recovery_interval_s": lambda: 15.0,
        "_recovery_max_age_s": lambda: 1800.0,
        "_current_execution_marker_ready": lambda: (bool(captured), "test"),
        "_writer_epoch_for_recovery": lambda: (True, "1"),
        "_canonical_kraken_broker": lambda: object(),
    }
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(PATCHER_PATH), "exec"), ns)
    return ns, captured, calls


def test_restart_recovery_accepts_five_value_trade_history_contract():
    ns, captured, calls = _recovery_namespace(fill=(100.0, 1.0, 100.0, 1, 9995.0))
    assert ns["_recover_recent_kraken_execution_proof"]()[0] is True
    assert captured[0]["broker_fill_at_epoch"] == 9995.0
    assert captured[0]["account"] == "platform:kraken"
    assert captured[0]["broker"] == "kraken"
    assert captured[0]["recovered_fill_proof"] is True
    assert calls == ["TradesHistory"]


@pytest.mark.parametrize("fill", [
    (100.0, 1.0, 100.0, 0, 9995.0),
    (100.0, 1.0, 100.0, 1, 0.0),
    (0.0, 1.0, 100.0, 1, 9995.0),
])
def test_restart_recovery_rejects_incomplete_exact_history(fill):
    ns, captured, _ = _recovery_namespace(fill=fill)
    assert ns["_recover_recent_kraken_execution_proof"]()[0] is False
    assert captured == []


def test_restart_recovery_does_not_promote_old_history():
    ns, captured, _ = _recovery_namespace(fill=(100.0, 1.0, 100.0, 1, 100.0), event_time=100.0)
    assert ns["_recover_recent_kraken_execution_proof"]()[0] is False
    assert captured == []


def test_restart_recovery_stops_without_writer_authority():
    ns, captured, calls = _recovery_namespace(fill=(100.0, 1.0, 100.0, 1, 9995.0))
    ns["_writer_epoch_for_recovery"] = lambda: (False, "writer_unproven")
    assert ns["_recover_recent_kraken_execution_proof"]() == (False, "writer_unproven")
    assert captured == [] and calls == []


def test_history_contract_repair_is_idempotent():
    patcher = _load_patcher()
    source = (ROOT / "bot/runtime_execution_position_readiness_v346_patch.py").read_text()
    once = patcher.patch_v346_text(source)
    assert patcher.patch_v346_text(once) == once
