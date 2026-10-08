"""Fail closed when Render starts NIJA: never fund a heartbeat liveness order.

Tests intentionally inspect production entrypoint text; they do not import
trading code, contact a broker, or submit an order.
"""
from pathlib import Path
import re

_ENTRYPOINT = Path(__file__).resolve().parents[2] / "scripts" / "render_entrypoint.sh"

def _exported(name: str) -> str:
    data = _ENTRYPOINT.read_text(encoding="utf-8")
    matches = re.findall(r"^\s*export\s+" + re.escape(name) + r"=([^\n#]+)", data, re.MULTILINE)
    assert matches, f"{name} must have an explicit production value"
    assert len(matches) == 1, f"{name} must not be ambiguously reassigned"
    return matches[0].strip().strip('"').strip("'").lower()

def test_production_heartbeat_orders_opted_out():
    assert _exported("NIJA_ALLOW_LIVE_HEARTBEAT_ORDERS") == "false"

def test_production_heartbeat_scheduler_opted_out():
    assert _exported("HEARTBEAT_TRADE") == "false"

def test_force_activation_and_trade_remain_disabled():
    assert _exported("NIJA_FORCE_ACTIVATION") == "false"
    assert _exported("FORCE_TRADE") == "false"
