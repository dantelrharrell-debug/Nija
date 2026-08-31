from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PATCH = ROOT / "bot" / "runtime_platform_position_sync_isolation_v320_patch.py"
V319 = ROOT / "bot" / "runtime_kraken_recent_balance_prewait_v319_patch.py"


def test_v320_requires_v285_strong_status_and_filters_only_activation_denominator() -> None:
    text = PATCH.read_text(encoding="utf-8")
    tree = ast.parse(text)

    assert "20260829-authoritative-position-coverage-v285" in text
    assert "position_sync_status_v285" in text
    assert 'str(name).startswith("platform:")' in text
    assert 'str(name).startswith("user:")' in text
    assert "bool(status) and not pending" in text
    assert "all_connected_platform_required=true" in text
    assert "v281_v282_v283_all_account_coverage_unchanged=true" in text
    assert "user_entries_fail_closed=true" in text
    assert "user_exits_preserved=true" in text
    assert "user_readiness_fabricated=false" in text
    assert "platform_readiness_fabricated=false" in text
    assert "forced_activation=false" in text
    assert "safety_gates_bypassed=false" in text
    assert isinstance(tree, ast.Module)


def test_v320_is_chained_from_existing_canonical_v319_installer() -> None:
    text = V319.read_text(encoding="utf-8")
    assert "runtime_platform_position_sync_isolation_v320_patch" in text
    assert "_install_platform_position_isolation_v320" in text
    assert "platform_position_isolation_v320=true" in text


def test_v320_does_not_mutate_user_broker_readiness_or_issue_broker_io() -> None:
    text = PATCH.read_text(encoding="utf-8")
    forbidden = (
        "_startup_position_sync_adopted = True",
        "_startup_position_sync_fetch_ok = True",
        "get_positions(",
        "connect(",
        "place_order(",
        "place_market_order(",
        "place_limit_order(",
        "set_ready(\"user",
    )
    for token in forbidden:
        assert token not in text
