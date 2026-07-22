from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PATCHER = ROOT / "apply_bot_package_defer_fix.py"
BOT_INIT = ROOT / "bot" / "__init__.py"


def _load_patcher():
    spec = importlib.util.spec_from_file_location("apply_bot_package_defer_fix", PATCHER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sample() -> str:
    return (
        "def _truthy(name):\n"
        "    return False\n\n"
        "try:\n"
        "    importlib.import_module(\"sitecustomize\")\n"
        "except Exception as _exc:\n"
        "    logger.warning(\"NIJA startup patch unavailable: %s\", _exc)\n"
        "_PATCH_HOOKS = (\n"
        "    (\"one\", \"One\"),\n"
        ")\n"
        "for _module_name, _label in _PATCH_HOOKS:\n"
        "    pass\n"
    )


def test_bot_package_patch_defers_sitecustomize_and_patch_loop() -> None:
    module = _load_patcher()
    patched = module.patch_text(_sample())

    assert '_NIJA_BOT_PACKAGE_RUNTIME_HOOKS_DEFERRED = _truthy("NIJA_DEFER_RUNTIME_SITE_HOOKS")' in patched
    assert "if _NIJA_BOT_PACKAGE_RUNTIME_HOOKS_DEFERRED:" in patched
    assert "_PATCH_HOOKS = () if _NIJA_BOT_PACKAGE_RUNTIME_HOOKS_DEFERRED else (" in patched
    assert "NIJA_BOT_PACKAGE_RUNTIME_HOOKS_DEFERRED runtime_site_hooks=deferred" in patched


def test_bot_package_patch_is_idempotent() -> None:
    module = _load_patcher()
    first = module.patch_text(_sample())
    second = module.patch_text(first)
    assert second == first


def test_repository_bot_init_is_patchable() -> None:
    module = _load_patcher()
    source = BOT_INIT.read_text(encoding="utf-8")
    patched = module.patch_text(source)
    assert "_PATCH_HOOKS = () if _NIJA_BOT_PACKAGE_RUNTIME_HOOKS_DEFERRED else (" in patched
