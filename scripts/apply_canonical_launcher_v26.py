"""Make start.sh launch NIJA through the pre-import v26 runtime launcher."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
START_PATH = ROOT / "start.sh"
OLD_LAUNCH = "$PY -u main.py"
NEW_LAUNCH = "$PY -u scripts/canonical_runtime_launcher_v26.py"
MARKER = "20260724-canonical-runtime-launcher-v26"


def patch_text(text: str) -> str:
    if NEW_LAUNCH in text:
        patched = text
    elif OLD_LAUNCH in text:
        patched = text.replace(OLD_LAUNCH, NEW_LAUNCH, 1)
    else:
        raise RuntimeError("start.sh canonical Python launch anchor not found")

    if patched.count(NEW_LAUNCH) != 1:
        raise RuntimeError("start.sh must contain exactly one canonical v26 launch")
    if OLD_LAUNCH in patched:
        raise RuntimeError("legacy direct main.py launch remains in start.sh")
    return patched


def main() -> None:
    original = START_PATH.read_text(encoding="utf-8")
    patched = patch_text(original)
    START_PATH.write_text(patched, encoding="utf-8")
    print(
        "CANONICAL_RUNTIME_LAUNCHER_V26_PATCH_APPLIED "
        f"marker={MARKER} launch=scripts/canonical_runtime_launcher_v26.py "
        f"changed={patched != original} idempotent=true"
    )


if __name__ == "__main__":
    main()
