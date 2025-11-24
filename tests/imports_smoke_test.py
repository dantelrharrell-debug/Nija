import importlib
import pytest

candidates = [
    ("src.trading.tradingview_webhook", "tradingview_blueprint"),
    ("web.tradingview_webhook", "bp"),
    ("tradingview_webhook", "bp"),
    ("tradingview_webhook", "tradingview_blueprint"),
]

def test_tradingview_exports():
    """
    Smoke test: ensure at least one candidate module exports the expected attribute.
    This test imports candidate modules and checks for the presence of the named attribute.
    It will fail if none of the candidates export the expected name (helps catch regressions).
    """
    errors = {}
    successes = []

    for mod_name, attr in candidates:
        try:
            mod = importlib.import_module(mod_name)
        except Exception as e:
            errors[f"{mod_name}.{attr}"] = f"import error: {e}"
            continue

        if not hasattr(mod, attr):
            errors[f"{mod_name}.{attr}"] = "missing attribute"
            continue

        # found one candidate with the attribute
        successes.append(f"{mod_name}.{attr}")

    assert successes, f"No candidate modules exported expected attribute. Errors: {errors}"
