"""Install a Python startup guard for NIJA's deferred shell preflight.

Python processes normally import ``sitecustomize`` after processing ``.pth``
files. NIJA's shell preflight intentionally sets
``NIJA_DEFER_RUNTIME_SITE_HOOKS=1`` so harmless validation commands cannot start
writer, broker, activation, or execution monitors before ``main.py``. The
existing .pth and ``bot.__init__`` guards did not stop Python's automatic
``sitecustomize`` import.

This installer creates an early .pth file that places a no-op ``sitecustomize``
module in ``sys.modules`` only for deferred preflight processes. The canonical
``main.py`` process starts after the flag is removed and therefore imports the
real ``sitecustomize.py`` normally.
"""

from __future__ import annotations

import site
from pathlib import Path

FILENAME = "0000_nija_sitecustomize_defer_guard.pth"
DEFER_FLAG = "NIJA_DEFER_RUNTIME_SITE_HOOKS"


def guard_content(app_root: str = "/app") -> str:
    root = str(app_root or "/app").rstrip("/") or "/app"
    code = (
        'import os,sys,types; '
        f'os.environ.get("{DEFER_FLAG}", "0") == "1" and '
        'sys.modules.setdefault("sitecustomize", types.ModuleType("sitecustomize"))'
    )
    return f"{root}\n{code}\n"


def install(site_packages: Path | None = None, app_root: str = "/app") -> Path:
    if site_packages is None:
        candidates = site.getsitepackages()
        if not candidates:
            raise RuntimeError("Python site-packages directory not found")
        site_packages = Path(candidates[0])
    site_packages = Path(site_packages)
    site_packages.mkdir(parents=True, exist_ok=True)
    target = site_packages / FILENAME
    target.write_text(guard_content(app_root), encoding="utf-8")
    return target


def main() -> None:
    target = install()
    print(
        "NIJA_SITECUSTOMIZE_DEFER_GUARD_INSTALLED "
        f"path={target} flag={DEFER_FLAG}"
    )


if __name__ == "__main__":
    main()
