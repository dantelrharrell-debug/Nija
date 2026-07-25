from __future__ import annotations

import ast
import importlib
import logging
import sys
from pathlib import Path
from types import ModuleType
from uuid import uuid4


SITECUSTOMIZE_PATH = Path(__file__).resolve().parents[2] / "sitecustomize.py"


def _load_patch_installer(sitecustomize_file: Path):
    tree = ast.parse(SITECUSTOMIZE_PATH.read_text(encoding="utf-8"))
    function = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_install_patch_module"
    )
    isolated = ast.Module(body=[function], type_ignores=[])
    ast.fix_missing_locations(isolated)
    namespace = {
        "__file__": str(sitecustomize_file),
        "importlib": importlib,
        "logger": logging.getLogger("test.sitecustomize.patch_loader"),
        "Path": Path,
        "sys": sys,
    }
    exec(compile(isolated, str(SITECUSTOMIZE_PATH), "exec"), namespace)
    return namespace["_install_patch_module"]


def test_path_loaded_patch_is_published_before_installer_runs(tmp_path) -> None:
    bot_dir = tmp_path / "bot"
    bot_dir.mkdir()
    filename = "sample_runtime_patch.py"
    (bot_dir / filename).write_text(
        "import sys\n"
        "PUBLISHED_DURING_INSTALL = False\n"
        "def install_import_hook():\n"
        "    global PUBLISHED_DURING_INSTALL\n"
        "    PUBLISHED_DURING_INSTALL = sys.modules.get(__name__) is not None\n",
        encoding="utf-8",
    )
    module_name = f"nija_test_runtime_patch_{uuid4().hex}"
    installer = _load_patch_installer(tmp_path / "sitecustomize.py")

    try:
        installer(
            filename=filename,
            module_name=module_name,
            success_log="TEST_PATCH_INSTALLED",
            error_prefix="test patch",
        )
        module = sys.modules.get(module_name)
        assert module is not None
        assert module.PUBLISHED_DURING_INSTALL is True
    finally:
        sys.modules.pop(module_name, None)


def test_failed_patch_load_restores_previous_module(tmp_path) -> None:
    bot_dir = tmp_path / "bot"
    bot_dir.mkdir()
    filename = "broken_runtime_patch.py"
    (bot_dir / filename).write_text("raise RuntimeError('broken patch')\n", encoding="utf-8")
    module_name = f"nija_test_runtime_patch_{uuid4().hex}"
    previous = ModuleType(module_name)
    sys.modules[module_name] = previous
    installer = _load_patch_installer(tmp_path / "sitecustomize.py")

    try:
        installer(
            filename=filename,
            module_name=module_name,
            success_log="TEST_PATCH_INSTALLED",
            error_prefix="test patch",
        )
        assert sys.modules.get(module_name) is previous
    finally:
        sys.modules.pop(module_name, None)
