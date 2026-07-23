from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
INSTALLER = ROOT / "scripts" / "install_sitecustomize_defer_guard.py"


def _load_installer():
    spec = importlib.util.spec_from_file_location(
        "install_sitecustomize_defer_guard", INSTALLER
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_guard_content_is_silent_and_flag_scoped() -> None:
    module = _load_installer()
    content = module.guard_content("/app")
    assert content.startswith("/app\nimport os,sys,types;")
    assert "NIJA_DEFER_RUNTIME_SITE_HOOKS" in content
    assert 'sys.modules.setdefault("sitecustomize"' in content
    assert "print(" not in content


def test_deferred_python_does_not_execute_real_sitecustomize(tmp_path: Path) -> None:
    module = _load_installer()
    venv = tmp_path / "venv"
    subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True)

    if os.name == "nt":
        python = venv / "Scripts" / "python.exe"
        site_packages = next((venv / "Lib" / "site-packages",), None)
    else:
        python = venv / "bin" / "python"
        site_packages = next((venv / "lib").glob("python*/site-packages"))

    app_root = tmp_path / "app"
    app_root.mkdir()
    marker = tmp_path / "sitecustomize-ran.txt"
    (app_root / "sitecustomize.py").write_text(
        "from pathlib import Path\n"
        f"Path({str(marker)!r}).write_text('ran', encoding='utf-8')\n",
        encoding="utf-8",
    )
    module.install(site_packages=site_packages, app_root=str(app_root))

    env = os.environ.copy()
    env["NIJA_DEFER_RUNTIME_SITE_HOOKS"] = "1"
    result = subprocess.run(
        [python, "-c", "import sitecustomize; print(sitecustomize.__name__)"],
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    assert result.stdout.strip() == "sitecustomize"
    assert not marker.exists()

    env.pop("NIJA_DEFER_RUNTIME_SITE_HOOKS", None)
    subprocess.run(
        [python, "-c", "import sitecustomize"],
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    assert marker.read_text(encoding="utf-8") == "ran"
