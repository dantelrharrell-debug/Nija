"""Patch start.sh so preflight Python cannot activate NIJA runtime hooks.

The Docker image installs several .pth startup hooks. Ordinary Python helper
commands in start.sh previously processed those hooks before main.py launched,
which could enter writer-lock standby during shell preflight and leave only the
Render liveness server running. This build-time patch adds an explicit defer
window and a visible handoff checkpoint around the canonical runtime launch.
"""
from __future__ import annotations

from pathlib import Path

START_PATH = Path("/app/start.sh")
DEFER_FLAG = "NIJA_DEFER_RUNTIME_SITE_HOOKS"


def patch_text(text: str) -> str:
    preflight_anchor = "_validate_redis_url_or_exit\n_log_redis_lock_source_hint\n"
    preflight_replacement = (
        'export NIJA_DEFER_RUNTIME_SITE_HOOKS=1\n'
        'echo "🧭 STARTUP_HANDOFF_PREFLIGHT_BEGIN runtime_site_hooks=deferred"\n'
        "_validate_redis_url_or_exit\n"
        "_log_redis_lock_source_hint\n"
        'echo "🧭 STARTUP_HANDOFF_REDIS_VALIDATION_COMPLETE"\n'
    )
    if preflight_anchor not in text and "STARTUP_HANDOFF_PREFLIGHT_BEGIN" not in text:
        raise RuntimeError("start.sh preflight anchor not found")
    text = text.replace(preflight_anchor, preflight_replacement, 1)

    launch_anchor = "set +e\n$PY -u main.py\nstatus=$?\n"
    launch_replacement = (
        f"unset {DEFER_FLAG}\n"
        'echo "🚀 STARTUP_HANDOFF_RUNTIME_BEGIN entrypoint=main.py runtime_site_hooks=enabled"\n'
        "set +e\n"
        "$PY -u main.py\n"
        "status=$?\n"
        'echo "🧭 STARTUP_HANDOFF_RUNTIME_EXIT status=${status}"\n'
    )
    if launch_anchor not in text and "STARTUP_HANDOFF_RUNTIME_BEGIN" not in text:
        raise RuntimeError("start.sh runtime launch anchor not found")
    text = text.replace(launch_anchor, launch_replacement, 1)
    return text


def main() -> None:
    original = START_PATH.read_text(encoding="utf-8")
    patched = patch_text(original)
    START_PATH.write_text(patched, encoding="utf-8")
    print("NIJA_STARTUP_HANDOFF_PATCH_APPLIED")


if __name__ == "__main__":
    main()
