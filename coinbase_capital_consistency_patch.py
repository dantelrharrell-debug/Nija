"""Early loader for Coinbase capital safety and read-only restart rehydration."""
from __future__ import annotations

import importlib.util
import pathlib
import sys

_ROOT = pathlib.Path(__file__).resolve().parent
_NAME = "nija_coinbase_capital_consistency_patch"
_PATH = _ROOT / "bot" / "coinbase_capital_consistency_patch.py"
_REHYDRATE_NAME = "nija_coinbase_capital_readonly_rehydrate_v388_patch"
_REHYDRATE_PATH = _ROOT / "bot" / "coinbase_capital_readonly_rehydrate_v388_patch.py"
_ALIAS_NAME = "nija_coinbase_capital_rehydrate_alias_v389_patch"
_ALIAS_PATH = _ROOT / "bot" / "coinbase_capital_rehydrate_alias_v389_patch.py"


def _load_named(name: str, path: pathlib.Path):
    module = sys.modules.get(name)
    if module is not None:
        return module
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"unable to load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _load():
    return _load_named(_NAME, _PATH)


def install() -> bool:
    main = _load()
    main_ok = bool(main.install())
    rehydrate = _load_named(_REHYDRATE_NAME, _REHYDRATE_PATH)
    rehydrate_ok = bool(rehydrate.install())
    alias = _load_named(_ALIAS_NAME, _ALIAS_PATH)
    alias_ok = bool(alias.install())
    return main_ok and rehydrate_ok and alias_ok


install()

__all__ = ["install"]
