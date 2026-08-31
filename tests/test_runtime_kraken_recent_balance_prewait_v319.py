from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BOT_ENTRY = ROOT / "bot" / "bot.py"
PATCH = ROOT / "bot" / "runtime_kraken_recent_balance_prewait_v319_patch.py"


def test_v319_installs_after_v318_and_before_bot_main() -> None:
    text = BOT_ENTRY.read_text(encoding="utf-8")
    v318 = '("bot.runtime_kraken_precore_liveness_v318_patch", "KRAKEN_PRECORE_LIVENESS_V318")'
    v319 = '("bot.runtime_kraken_recent_balance_prewait_v319_patch", "KRAKEN_RECENT_BALANCE_PREWAIT_V319")'
    assert v318 in text and v319 in text
    assert text.index(v318) < text.index(v319) < text.index("from bot.bot_main import main")


def test_v319_reuses_only_authenticated_v312_observation_without_rate_bypass() -> None:
    text = PATCH.read_text(encoding="utf-8")
    tree = ast.parse(text)

    assert "_fresh_observation" in text
    assert "not_before=0.0" in text
    assert "NIJA_RUNTIME_KRAKEN_BALANCE_EPOCH_HANDOFF_V312_READY" in text
    assert 'state != "LIVE_ACTIVE"' in text
    assert "configured_rate_interval_unchanged=true" in text
    assert "v312_cache_ttl_unchanged=true" in text
    assert "position_snapshot_ttl_unchanged=true" in text
    assert "same_epoch_timeout_recovery_unchanged=true" in text
    assert "lock_bypass=false" in text
    assert "lock_force_release=false" in text
    assert "position_success_fabricated=false" in text
    assert "execution_proof_fabricated=false" in text

    # v319 is a pure handoff wrapper; it must never issue Kraken broker I/O.
    assert "_kraken_private_call(" not in text
    assert "get_positions(" not in text
    assert "time.sleep(" not in text
    assert isinstance(tree, ast.Module)
