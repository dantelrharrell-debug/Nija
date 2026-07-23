"""Fail-closed attestation for the canonical NIJA production entrypoint.

This script intentionally uses only the Python standard library and never imports the
``bot`` package. It is safe to run with ``python -S`` while runtime site hooks are
deferred. The goal is to prove that the deployed image contains the canonical path
and the current broker-prebootstrap safeguards before the live Python process starts.
"""
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path

_MARKER = "20260723-runtime-entrypoint-attestation-v23"
_CANONICAL_PATH = "main.py->bot.bot->bot.bot_main"
_PLACEHOLDERS = {"", "unknown", "none", "null", "unset", "n/a", "na"}


@dataclass(frozen=True)
class FileContract:
    relative_path: str
    required_markers: tuple[str, ...]


_CONTRACTS = (
    FileContract(
        "main.py",
        ('runpy.run_module("bot.bot", run_name="__main__")',),
    ),
    FileContract(
        "bot/bot.py",
        (
            "canonical_broker_prebootstrap_v22",
            "stalled_writer_release_guard_v22",
            "from bot.bot_main import main",
        ),
    ),
    FileContract(
        "bot/bot_main.py",
        (
            "_acquire_writer_authority_before_nonce",
            "_run_self_healing_startup",
            "_release_writer_authority",
        ),
    ),
    FileContract(
        "bot/canonical_broker_prebootstrap_v22.py",
        (
            "20260723-canonical-broker-prebootstrap-v22",
            "prepare_canonical_broker_runtime",
        ),
    ),
    FileContract(
        "bot/stalled_writer_release_guard_v22.py",
        (
            "20260723-stalled-writer-release-v22",
            "STALLED_WRITER_RELEASE_GUARD_V22_TRIGGERED",
        ),
    ),
)


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on", "enabled"}


def _first_provenance(names: tuple[str, ...]) -> str:
    """Return the first meaningful provider value, skipping placeholders."""

    for name in names:
        value = str(os.environ.get(name, "") or "").strip()
        if value.lower() not in _PLACEHOLDERS:
            return value
    return "unknown"


def _short_hash(path: Path) -> str:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return digest[:12]


def _live_intent() -> bool:
    if _truthy(os.environ.get("DRY_RUN_MODE")) or _truthy(os.environ.get("PAPER_MODE")):
        return False
    return _truthy(os.environ.get("LIVE_CAPITAL_VERIFIED")) or _truthy(
        os.environ.get("NIJA_EXECUTION_ACTIVE")
    ) or str(os.environ.get("NIJA_RUNTIME_TRADING_STATE", "")).strip().upper() in {
        "LIVE_PENDING_CONFIRMATION",
        "LIVE_ACTIVE",
    }


def validate_runtime(root: Path) -> dict[str, str]:
    root = root.resolve()
    hashes: list[str] = []
    for contract in _CONTRACTS:
        path = root / contract.relative_path
        if not path.is_file():
            raise RuntimeError(f"required runtime file missing: {contract.relative_path}")
        text = path.read_text(encoding="utf-8")
        missing = [marker for marker in contract.required_markers if marker not in text]
        if missing:
            raise RuntimeError(
                f"runtime contract mismatch: {contract.relative_path} missing={','.join(missing)}"
            )
        hashes.append(f"{contract.relative_path}:{_short_hash(path)}")

    commit = _first_provenance(
        ("GIT_COMMIT", "RENDER_GIT_COMMIT", "RAILWAY_GIT_COMMIT_SHA")
    )
    branch = _first_provenance(
        ("GIT_BRANCH", "RENDER_GIT_BRANCH", "RAILWAY_GIT_BRANCH")
    )
    if _live_intent() and commit.lower() in _PLACEHOLDERS:
        raise RuntimeError("live runtime commit provenance is unknown")

    return {
        "marker": _MARKER,
        "canonical": _CANONICAL_PATH,
        "commit": commit,
        "branch": branch,
        "hashes": ",".join(hashes),
    }


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    try:
        report = validate_runtime(root)
    except Exception as exc:
        print(
            "RUNTIME_ENTRYPOINT_ATTESTATION_FAILED "
            f"marker={_MARKER} canonical={_CANONICAL_PATH} "
            f"type={type(exc).__name__} error={exc}",
            flush=True,
        )
        return 78

    print(
        "RUNTIME_ENTRYPOINT_ATTESTATION_OK "
        f"marker={report['marker']} canonical={report['canonical']} "
        f"branch={report['branch']} commit={report['commit']} hashes={report['hashes']}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
