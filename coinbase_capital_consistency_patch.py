"""Early loader for the canonical Coinbase capital consistency guard."""
from __future__ import annotations

import importlib.util
import pathlib
import sys

_NAME = "nija_coinbase_capital_consistency_patch"
_PATH = pathlib.Path(__file__).resolve().parent / "bot" / "coinbase_capital_consistency_patch.py"


def _load():
    module = sys.modules.get(_NAME)
    if module is not None:
        return module
    spec = importlib.util.spec_from_file_location(_NAME, _PATH)
    if spec is None or spec.loader is None:
        raise ImportError(f"unable to load {_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[_NAME] = module
    spec.loader.exec_module(module)
    return module


def install() -> bool:
    module = _load()
    return bool(module.install())


install()

__all__ = ["install"]
