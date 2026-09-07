#!/usr/bin/env python3
"""Wire the v387 non-ordering Kraken four-way supervisor into bot fast startup."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "bot" / "bot.py"
MARKER = "20260907-kraken-margin-four-way-supervisor-v387"
SPEC = '    ("bot.runtime_kraken_margin_four_way_supervisor_v387_patch", "KRAKEN_MARGIN_FOUR_WAY_SUPERVISOR_V387"),\n'
ANCHOR = '    ("bot.runtime_kraken_recent_balance_prewait_v319_patch", "KRAKEN_RECENT_BALANCE_PREWAIT_V319"),\n'


def main() -> None:
    text = TARGET.read_text(encoding="utf-8")
    changed = False
    if SPEC not in text:
        if ANCHOR not in text:
            raise RuntimeError("canonical fast-path v319 anchor not found")
        text = text.replace(ANCHOR, ANCHOR + SPEC, 1)
        TARGET.write_text(text, encoding="utf-8")
        changed = True
    print(
        "KRAKEN_MARGIN_FOUR_WAY_SUPERVISOR_V387_PATCH_APPLIED "
        f"marker={MARKER} changed={str(changed).lower()} canonical_fast_path=true "
        "nonordering_supervisor=true full_v368_installer=false native_backup_started=false "
        "orders_submitted=false safety_gates_bypassed=false"
    )


if __name__ == "__main__":
    main()
