from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PATCHER = ROOT / "scripts" / "apply_canonical_launcher_v26.py"


def _load_patcher():
    spec = importlib.util.spec_from_file_location(
        "test_entry_price_single_flight_identity_v316_patcher",
        PATCHER,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _fixture() -> str:
    return '''def _bounded_real_entry_price(broker: Any, symbol: str) -> Tuple[float, str]:
    method = getattr(broker, "get_real_entry_price", None)
    if not callable(method):
        return 0.0, "api_unavailable"

    normalized_symbol = str(symbol or "").strip().upper()
    key = (id(broker), normalized_symbol)
    started_new = False
    return 0.0, "api_empty"
'''


def test_v316_replaces_ephemeral_proxy_identity_with_bound_method_owner() -> None:
    patcher = _load_patcher()
    patched = patcher.patch_position_sync_text(_fixture())

    assert 'method_owner = getattr(method, "__self__", None)' in patched
    assert "identity_broker = method_owner if method_owner is not None else broker" in patched
    assert "key = (id(identity_broker), normalized_symbol)" in patched
    assert "key = (id(broker), normalized_symbol)" not in patched


def test_v316_transform_is_idempotent() -> None:
    patcher = _load_patcher()
    once = patcher.patch_position_sync_text(_fixture())
    twice = patcher.patch_position_sync_text(once)
    assert twice == once


def test_v316_does_not_change_timeout_or_cost_basis_fallback_policy() -> None:
    patcher = _load_patcher()
    patched = patcher.patch_position_sync_text(_fixture())

    assert "NIJA_POSITION_ENTRY_PRICE_TIMEOUT_S" not in patched
    assert "current_price" not in patched
    assert "entry_price =" not in patched
