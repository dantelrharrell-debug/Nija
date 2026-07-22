"""Patch ``start.sh`` so preflight Python cannot activate NIJA runtime hooks.

The Docker image installs several ``.pth`` startup hooks. Every Python process
started before ``main.py`` must see ``NIJA_DEFER_RUNTIME_SITE_HOOKS=1``;
otherwise a harmless preflight command can acquire writer authority or enter
standby before the canonical trading runtime starts.

The patch is intentionally idempotent because Docker rebuilds and operator
recovery scripts may apply it more than once.
"""
from __future__ import annotations

import re
from pathlib import Path

START_PATH = Path("/app/start.sh")
DEFER_FLAG = "NIJA_DEFER_RUNTIME_SITE_HOOKS"
PREFLIGHT_MARKER = "STARTUP_HANDOFF_PREFLIGHT_BEGIN"
REDIS_MARKER = "STARTUP_HANDOFF_REDIS_VALIDATION_COMPLETE"
RUNTIME_MARKER = "STARTUP_HANDOFF_RUNTIME_BEGIN"
RUNTIME_EXIT_MARKER = "STARTUP_HANDOFF_RUNTIME_EXIT"


def _insert_early_defer(text: str) -> str:
    if PREFLIGHT_MARKER in text:
        return text

    block = (
        f"export {DEFER_FLAG}=1\n"
        'echo "🧭 STARTUP_HANDOFF_PREFLIGHT_BEGIN runtime_site_hooks=deferred"\n'
    )

    set_match = re.search(r"(?m)^set -e(?:uo pipefail)?(?:\s+#.*)?$", text)
    if set_match:
        insert_at = set_match.end()
        return text[:insert_at] + "\n" + block + text[insert_at:]

    if text.startswith("#!"):
        newline = text.find("\n")
        if newline >= 0:
            return text[: newline + 1] + block + text[newline + 1 :]

    return block + text


def _insert_redis_checkpoint(text: str) -> str:
    if REDIS_MARKER in text:
        return text

    anchor = "_validate_redis_url_or_exit\n_log_redis_lock_source_hint\n"
    if anchor not in text:
        raise RuntimeError("start.sh Redis preflight anchor not found")
    return text.replace(
        anchor,
        anchor + 'echo "🧭 STARTUP_HANDOFF_REDIS_VALIDATION_COMPLETE"\n',
        1,
    )


def _insert_runtime_handoff(text: str) -> str:
    if RUNTIME_MARKER in text:
        return text

    anchor = "set +e\n$PY -u main.py\nstatus=$?\n"
    if anchor not in text:
        raise RuntimeError("start.sh runtime launch anchor not found")
    replacement = (
        f"unset {DEFER_FLAG}\n"
        'echo "🚀 STARTUP_HANDOFF_RUNTIME_BEGIN entrypoint=main.py runtime_site_hooks=enabled"\n'
        "set +e\n"
        "$PY -u main.py\n"
        "status=$?\n"
        'echo "🧭 STARTUP_HANDOFF_RUNTIME_EXIT status=${status}"\n'
    )
    return text.replace(anchor, replacement, 1)


def _validate(text: str) -> None:
    for marker in (PREFLIGHT_MARKER, REDIS_MARKER, RUNTIME_MARKER, RUNTIME_EXIT_MARKER):
        if text.count(marker) != 1:
            raise RuntimeError(f"startup handoff marker count invalid: {marker}")

    export_pos = text.index(f"export {DEFER_FLAG}=1")
    unset_pos = text.index(f"unset {DEFER_FLAG}")
    main_pos = text.index("$PY -u main.py")
    if not export_pos < unset_pos < main_pos:
        raise RuntimeError("startup handoff ordering invalid")

    pre_main = text[:main_pos]
    python_tokens = ("$PY ", '"${PY}" ', "${PY} ", "python3 ", "python ")
    early_positions = [pre_main.find(token) for token in python_tokens]
    early_positions = [position for position in early_positions if position >= 0]
    if early_positions and export_pos > min(early_positions):
        raise RuntimeError("runtime hooks are not deferred before the first Python preflight")


def patch_text(text: str) -> str:
    patched = _insert_early_defer(text)
    patched = _insert_redis_checkpoint(patched)
    patched = _insert_runtime_handoff(patched)
    _validate(patched)
    return patched


def main() -> None:
    original = START_PATH.read_text(encoding="utf-8")
    patched = patch_text(original)
    START_PATH.write_text(patched, encoding="utf-8")
    print("NIJA_STARTUP_HANDOFF_PATCH_APPLIED early_defer=true idempotent=true")


if __name__ == "__main__":
    main()
