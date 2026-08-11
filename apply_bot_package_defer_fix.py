"""Make ``bot`` package imports honor the startup runtime-hook defer flag.

``start.sh`` runs a few Python preflight helpers that import ``bot.*`` modules.
Importing a submodule executes ``bot/__init__.py`` first. Historically that
package initializer imported ``sitecustomize`` and installed dozens of runtime
patch hooks unconditionally, bypassing the Docker ``.pth`` defer guard.

This build-time patch keeps harmless environment normalization available during
preflight while skipping sitecustomize and the package patch-hook loop whenever
``NIJA_DEFER_RUNTIME_SITE_HOOKS=1``. The canonical ``main.py`` process starts
after the flag is removed, so the complete runtime hook stack still installs.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent
BOT_INIT_PATH = Path("/app/bot/__init__.py")
if not BOT_INIT_PATH.exists():
    BOT_INIT_PATH = ROOT / "bot" / "__init__.py"

DEFER_NAME = "_NIJA_BOT_PACKAGE_RUNTIME_HOOKS_DEFERRED"
MARKER = "NIJA_BOT_PACKAGE_RUNTIME_HOOKS_DEFERRED"
MARKER_LOG_LITERAL = f'"{MARKER} runtime_site_hooks=deferred"'

_SITE_ANCHOR = (
    'try:\n'
    '    importlib.import_module("sitecustomize")\n'
    'except Exception as _exc:\n'
    '    logger.warning("NIJA startup patch unavailable: %s", _exc)\n'
)
_SITE_REPLACEMENT = (
    f'{DEFER_NAME} = _truthy("NIJA_DEFER_RUNTIME_SITE_HOOKS")\n'
    f'if {DEFER_NAME}:\n'
    f'    logger.info("{MARKER} runtime_site_hooks=deferred")\n'
    'else:\n'
    '    try:\n'
    '        importlib.import_module("sitecustomize")\n'
    '    except Exception as _exc:\n'
    '        logger.warning("NIJA startup patch unavailable: %s", _exc)\n'
)
_HOOKS_ANCHOR = "_PATCH_HOOKS = (\n"
_HOOKS_REPLACEMENT = f"_PATCH_HOOKS = () if {DEFER_NAME} else (\n"
_BOUNDED_STARTUP_COMMENT_MARKER = "side-effect bounded"
_BOUNDED_STARTUP_LOG_MARKER = "BOT_PACKAGE_STARTUP_BOUNDED"


def _is_already_patched(text: str) -> bool:
    has_defer_assignment = f"{DEFER_NAME} =" in text
    has_deferred_log_marker = MARKER in text
    has_bounded_startup_comment = _BOUNDED_STARTUP_COMMENT_MARKER in text
    has_bounded_startup_log_marker = _BOUNDED_STARTUP_LOG_MARKER in text

    return (has_defer_assignment and has_deferred_log_marker) or (
        has_bounded_startup_comment and has_bounded_startup_log_marker
    )


def _validate(text: str) -> None:
    if text.count(f"{DEFER_NAME} =") != 1:
        raise RuntimeError("bot package defer assignment count invalid")
    if text.count(MARKER_LOG_LITERAL) != 1:
        raise RuntimeError("bot package defer log marker count invalid")
    if text.count(_HOOKS_REPLACEMENT) != 1:
        raise RuntimeError("bot package patch-hook defer guard count invalid")
    if text.index(f"{DEFER_NAME} =") > text.index(_HOOKS_REPLACEMENT):
        raise RuntimeError("bot package defer guard ordering invalid")


def patch_text(text: str) -> str:
    if _is_already_patched(text):
        return text

    if f"{DEFER_NAME} =" not in text:
        if _SITE_ANCHOR not in text:
            raise RuntimeError("bot/__init__.py sitecustomize anchor not found")
        text = text.replace(_SITE_ANCHOR, _SITE_REPLACEMENT, 1)

    if _HOOKS_REPLACEMENT not in text:
        if _HOOKS_ANCHOR not in text:
            raise RuntimeError("bot/__init__.py patch-hook anchor not found")
        text = text.replace(_HOOKS_ANCHOR, _HOOKS_REPLACEMENT, 1)

    _validate(text)
    return text


def main() -> None:
    original = BOT_INIT_PATH.read_text(encoding="utf-8")
    patched = patch_text(original)
    changed = patched != original
    if changed:
        BOT_INIT_PATH.write_text(patched, encoding="utf-8")
    print(f"NIJA_BOT_PACKAGE_DEFER_PATCH_APPLIED idempotent=true changed={str(changed).lower()}")


if __name__ == "__main__":
    main()
