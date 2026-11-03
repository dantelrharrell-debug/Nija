"""Regression tests for mobile endpoints without authoritative account data."""

import ast
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]


def _call_handler(handler_name, args=None):
    source = (ROOT / "mobile_api.py").read_text(encoding="utf-8")
    module = ast.parse(source)
    functions = [
        node for node in module.body
        if isinstance(node, ast.FunctionDef)
        and node.name in {"_unavailable_mobile_data", handler_name}
    ]
    for function in functions:
        function.decorator_list = []
    namespace = {
        "request": SimpleNamespace(args=args or {}),
        "jsonify": lambda body: body,
        "_authenticated_user": lambda: "member-a",
    }
    exec(
        compile(ast.Module(body=functions, type_ignores=[]), str(ROOT / "mobile_api.py"), "exec"),
        namespace,
    )
    return namespace[handler_name]()


def test_dashboard_does_not_invent_zero_balance_or_performance():
    body, status = _call_handler("get_dashboard_summary")
    assert status == 503
    assert body["status"] == "unavailable"
    assert body["resource"] == "dashboard"
    assert "stats" not in body
    assert "account" not in body


def test_positions_are_not_reported_as_empty_when_source_is_unavailable():
    body, status = _call_handler("get_lightweight_positions")
    assert status == 503
    assert body["status"] == "unavailable"
    assert body["resource"] == "positions"
    assert "positions" not in body


def test_trades_are_not_reported_as_empty_when_source_is_unavailable():
    body, status = _call_handler("get_recent_trades", {"limit": "10"})
    assert status == 503
    assert body["status"] == "unavailable"
    assert body["resource"] == "trades"
    assert "trades" not in body


def test_mobile_config_does_not_advertise_unverified_capabilities():
    config = _call_handler("get_mobile_config")["config"]
    assert not any(config["features"].values())
    assert config["supported_exchanges"] == []


if __name__ == "__main__":
    for name, test in sorted(globals().items()):
        if name.startswith("test_") and callable(test):
            test()
    print("mobile unavailable-data regressions: PASS")
