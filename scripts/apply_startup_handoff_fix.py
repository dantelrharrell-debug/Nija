"""Patch ``start.sh`` so preflight Python cannot activate NIJA runtime hooks.

The Docker image installs several ``.pth`` startup hooks. Every Python process
started before the canonical launcher must see ``NIJA_DEFER_RUNTIME_SITE_HOOKS=1``;
otherwise a harmless preflight command can acquire writer authority or enter
standby before the canonical trading runtime starts.

The patch also replaces obsolete root-``bot.py`` diagnostics, runs a
standard-library-only runtime attestation, and permanently rewrites the runtime
launch to ``scripts/canonical_runtime_launcher_v26.py``. This makes the v26
ordering guard effective even when a platform overrides the Docker command with
``bash start.sh``.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT_PATH = Path(__file__).resolve().parents[1]
START_PATH = ROOT_PATH / "start.sh"
DEFER_FLAG = "NIJA_DEFER_RUNTIME_SITE_HOOKS"
PREFLIGHT_MARKER = "STARTUP_HANDOFF_PREFLIGHT_BEGIN"
REDIS_MARKER = "STARTUP_HANDOFF_REDIS_VALIDATION_COMPLETE"
ATTESTATION_MARKER = "STARTUP_HANDOFF_ENTRYPOINT_ATTESTATION_COMPLETE"
CANONICAL_DIAGNOSTIC_MARKER = "CANONICAL_ENTRYPOINT_DIAGNOSTICS"
RUNTIME_MARKER = "STARTUP_HANDOFF_RUNTIME_BEGIN"
RUNTIME_EXIT_MARKER = "STARTUP_HANDOFF_RUNTIME_EXIT"
LAUNCHER = "scripts/canonical_runtime_launcher_v26.py"
LEGACY_LAUNCH = "$PY -u main.py"
CANONICAL_LAUNCH = f"$PY -u {LAUNCHER}"


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


def _replace_legacy_entrypoint_diagnostics(text: str) -> str:
    if CANONICAL_DIAGNOSTIC_MARKER in text:
        return text
    pattern = re.compile(
        r'echo "🔄 Starting live trading bot\.\.\."\n.*?\n# Start the canonical Python entrypoint',
        re.DOTALL,
    )
    match = pattern.search(text)
    if match is None:
        return text
    replacement = (
        'echo "🔄 Starting live trading bot..."\n'
        'echo "Working directory: $(pwd)"\n'
        'echo "🧭 CANONICAL_ENTRYPOINT_DIAGNOSTICS path=launcher-v26->main.py->bot.bot->bot.bot_main release=v26"\n'
        'for _runtime_file in main.py bot/bot.py bot/bot_main.py '
        'bot/canonical_broker_prebootstrap_v22.py '
        'bot/canonical_broker_startup_convergence_v24.py '
        'bot/stalled_writer_release_guard_v22.py '
        'scripts/canonical_runtime_launcher_v26.py '
        'scripts/runtime_entrypoint_attestation.py; do\n'
        '    if [ ! -f "${_runtime_file}" ]; then\n'
        '        echo "❌ Canonical runtime file missing: ${_runtime_file}"\n'
        '        exit 78\n'
        '    fi\n'
        'done\n'
        f'{DEFER_FLAG}=1 $PY -S -m py_compile main.py bot/bot.py bot/bot_main.py '
        'bot/canonical_broker_prebootstrap_v22.py '
        'bot/canonical_broker_startup_convergence_v24.py '
        'bot/stalled_writer_release_guard_v22.py '
        'scripts/canonical_runtime_launcher_v26.py '
        'scripts/runtime_entrypoint_attestation.py\n'
        'echo "--- canonical bot/bot.py (head) ---"\n'
        'head -n 14 bot/bot.py || true\n'
        'echo "-----------------------------------"\n'
        'if ! grep -q "canonical_broker_prebootstrap_v22" bot/bot.py || '
        '! grep -q "stalled_writer_release_guard_v22" bot/bot.py || '
        '! grep -q "canonical_broker_startup_convergence_v24" bot/logging_format_guard_patch.py; then\n'
        '    echo "❌ Canonical v22/v24 entrypoint guards are missing"\n'
        '    exit 78\n'
        'fi\n\n'
        '# Start the canonical Python entrypoint'
    )
    return text[: match.start()] + replacement + text[match.end() :]


def _attestation_block() -> str:
    return (
        'echo "🧾 STARTUP_HANDOFF_ENTRYPOINT_ATTESTATION_BEGIN canonical=launcher-v26->main.py->bot.bot->bot.bot_main release=v26"\n'
        f'{DEFER_FLAG}=1 $PY -S scripts/runtime_entrypoint_attestation.py\n'
        'echo "🧾 STARTUP_HANDOFF_ENTRYPOINT_ATTESTATION_COMPLETE release=v26"\n'
    )


def _insert_runtime_handoff(text: str) -> str:
    if RUNTIME_MARKER in text:
        if ATTESTATION_MARKER not in text:
            unset_anchor = f"unset {DEFER_FLAG}\n"
            if unset_anchor not in text:
                raise RuntimeError("start.sh runtime defer-unset anchor not found")
            text = text.replace(unset_anchor, _attestation_block() + unset_anchor, 1)
        return text
    anchor = "set +e\n$PY -u main.py\nstatus=$?\n"
    if anchor not in text:
        raise RuntimeError("start.sh runtime launch anchor not found")
    replacement = (
        _attestation_block()
        + f"unset {DEFER_FLAG}\n"
        + 'echo "🚀 STARTUP_HANDOFF_RUNTIME_BEGIN entrypoint=canonical_runtime_launcher_v26.py '
        'canonical=launcher-v26->main.py->bot.bot->bot.bot_main runtime_site_hooks=enabled '
        'release=v26 commit=${GIT_COMMIT_SHORT:-${GIT_COMMIT:-unknown}}"\n'
        + "set +e\n"
        + CANONICAL_LAUNCH + "\n"
        + "status=$?\n"
        + 'echo "🧭 STARTUP_HANDOFF_RUNTIME_EXIT status=${status}"\n'
    )
    return text.replace(anchor, replacement, 1)


def _enforce_v26_launcher(text: str) -> str:
    text = text.replace(LEGACY_LAUNCH, CANONICAL_LAUNCH)
    if LEGACY_LAUNCH in text:
        raise RuntimeError("legacy direct main.py launch remains")
    if text.count(CANONICAL_LAUNCH) != 1:
        raise RuntimeError("canonical v26 launcher count invalid")
    return text


def _validate(text: str) -> None:
    for marker in (
        PREFLIGHT_MARKER,
        REDIS_MARKER,
        ATTESTATION_MARKER,
        RUNTIME_MARKER,
        RUNTIME_EXIT_MARKER,
    ):
        if text.count(marker) != 1:
            raise RuntimeError(f"startup handoff marker count invalid: {marker}")
    export_pos = text.index(f"export {DEFER_FLAG}=1")
    attestation_pos = text.index(ATTESTATION_MARKER)
    unset_pos = text.index(f"unset {DEFER_FLAG}")
    launcher_pos = text.index(CANONICAL_LAUNCH)
    if not export_pos < attestation_pos < unset_pos < launcher_pos:
        raise RuntimeError("startup handoff ordering invalid")
    if LEGACY_LAUNCH in text:
        raise RuntimeError("legacy direct main.py launch remains")
    pre_launcher = text[:launcher_pos]
    python_tokens = ("$PY ", '"${PY}" ', "${PY} ", "python3 ", "python ")
    early_positions = [pre_launcher.find(token) for token in python_tokens]
    early_positions = [position for position in early_positions if position >= 0]
    if early_positions and export_pos > min(early_positions):
        raise RuntimeError("runtime hooks are not deferred before the first Python preflight")


def patch_text(text: str) -> str:
    patched = _insert_early_defer(text)
    patched = _insert_redis_checkpoint(patched)
    patched = _replace_legacy_entrypoint_diagnostics(patched)
    patched = _insert_runtime_handoff(patched)
    patched = _enforce_v26_launcher(patched)
    _validate(patched)
    return patched


def main() -> None:
    original = START_PATH.read_text(encoding="utf-8")
    patched = patch_text(original)
    START_PATH.write_text(patched, encoding="utf-8")
    print(
        "NIJA_STARTUP_HANDOFF_PATCH_APPLIED "
        "early_defer=true canonical_attestation=true portable_root=true "
        "launcher=v26 release=v26 idempotent=true"
    )


if __name__ == "__main__":
    main()
