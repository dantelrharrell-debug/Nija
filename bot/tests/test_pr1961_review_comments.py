import re
from pathlib import Path


_CORE_LOOP_SOURCE = Path(__file__).resolve().parents[1] / "nija_core_loop.py"


def _core_loop_text() -> str:
    return _CORE_LOOP_SOURCE.read_text(encoding="utf-8")


def test_market_filter_unpack_accepts_optional_extra_values() -> None:
    text = _core_loop_text()
    assert re.search(
        r"allow,\s*trend,\s*market_reason,\s*\*_market_filter_extra\s*=\s*self\.apex\.check_market_filter\s*\(",
        text,
    )


def test_force_activation_checks_use_env_truthy_helper() -> None:
    text = _core_loop_text()
    assert '_env_truthy("FORCE_TRADE")' in text
    assert '_env_truthy("NIJA_FORCE_ACTIVATION")' in text
    assert '_env_truthy("FORCE_TRADE_MODE")' in text


def test_cycle_skip_signature_reset_is_guarded_by_open_gate_else_branch() -> None:
    text = _core_loop_text()
    assert re.search(r"else:(?:\s*#.*)?\s*\n\s*_last_cycle_skip_signature\s*=\s*None", text)
