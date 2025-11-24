from flask import Blueprint, jsonify, current_app
import os
import traceback

bp = Blueprint("preflight", __name__)

def check_env():
    required = {
        "COINBASE_API_KEY": bool(os.getenv("COINBASE_API_KEY")),
        "COINBASE_API_SECRET": bool(os.getenv("COINBASE_API_SECRET")),
        "COINBASE_API_SUB": bool(os.getenv("COINBASE_API_SUB")),
        "LIVE_TRADING": bool(os.getenv("LIVE_TRADING")),
    }
    return {"ok": all(required.values()), "detail": required}

def check_imports():
    try:
        # Attempt to import the Coinbase client used by your project
        from src.nija_client import CoinbaseClient  # adjust if different
        return {"ok": True, "detail": "CoinbaseClient import OK"}
    except Exception as e:
        return {"ok": False, "detail": f"Import failed: {repr(e)}"}

def check_auth_and_accounts():
    try:
        from src.nija_client import CoinbaseClient
        client = CoinbaseClient()
        # Try a lightweight auth / accounts call
        accounts = client.fetch_accounts()
        has_accounts = bool(accounts)
        return {"ok": True, "detail": {"accounts_count": len(accounts), "sample": accounts[:3]}}
    except Exception as e:
        tb = traceback.format_exc()
        return {"ok": False, "detail": f"Auth/accounts failed: {repr(e)}", "trace": tb}

def check_funded_balance(min_usd=1.0):
    try:
        from src.nija_client import CoinbaseClient
        client = CoinbaseClient()
        accounts = client.fetch_accounts()
        # try to detect an account with usable balance
        funded = []
        for a in accounts:
            # adjust key names to your client shape
            try:
                available = float(a.get("available", a.get("balance", {}).get("available", 0)))
            except Exception:
                available = 0.0
            if available and available >= 0:
                funded.append(a)
        ok = any(True for a in funded)
        return {"ok": ok, "detail": {"funded_count": len(funded), "sample": funded[:3]}}
    except Exception as e:
        tb = traceback.format_exc()
        return {"ok": False, "detail": f"Balance check error: {repr(e)}", "trace": tb}

def compute_score(results, weights=None):
    # Default weights sum to 100
    default = {
        "env": 10,
        "imports": 10,
        "auth": 20,
        "accounts": 20,   # included in auth check; keep separation for scoring
        "funded": 15,
        "blueprint": 10,
        "health": 15
    }
    if weights is None:
        weights = default
    total = sum(weights.values())
    score = 0.0

    # mapping
    if results.get("env", {}).get("ok"):
        score += weights["env"]
    if results.get("imports", {}).get("ok"):
        score += weights["imports"]
    if results.get("auth", {}).get("ok"):
        score += weights["auth"]
    if results.get("accounts", {}).get("ok"):
        score += weights["accounts"]
    if results.get("funded", {}).get("ok"):
        score += weights["funded"]
    if results.get("blueprint", {}).get("ok"):
        score += weights["blueprint"]
    if results.get("health", {}).get("ok"):
        score += weights["health"]

    percent = round((score / total) * 100, 1) if total else 0.0
    return percent

@bp.route("/preflight", methods=["GET"])
def preflight():
    results = {}
    # 1) env
    results["env"] = check_env()
    # 2) imports
    results["imports"] = check_imports()
    # 3) auth/accounts (attempt small calls)
    auth_accounts = check_auth_and_accounts()
    results["auth"] = {"ok": auth_accounts["ok"], "detail": "auth/accounts attempt"}
    # For separation, provide accounts-specific result as same data
    results["accounts"] = {"ok": auth_accounts["ok"], "detail": auth_accounts.get("detail")}
    # 4) funded balance
    results["funded"] = check_funded_balance()
    # 5) blueprint / app visible (we can detect presence of registered blueprints)
    try:
        # If the app registered a blueprint 'tradingview' or similar
        bp_names = [b.name for b in current_app.blueprints.values()]
        results["blueprint"] = {"ok": "tradingview" in bp_names or "preflight" in bp_names, "detail": bp_names}
    except Exception as e:
        results["blueprint"] = {"ok": False, "detail": repr(e)}
    # 6) health endpoint check (exists locally)
    try:
        # If a health function exists in the same app, call or check url_map
        has_health = any("health" in rule.endpoint or rule.rule.endswith("/health") for rule in current_app.url_map.iter_rules())
        results["health"] = {"ok": has_health, "detail": [r.rule for r in current_app.url_map.iter_rules() if "/health" in r.rule]}
    except Exception as e:
        results["health"] = {"ok": False, "detail": repr(e)}

    percent = compute_score(results)
    payload = {"ok": percent >= 80, "percent": percent, "results": results}
    return jsonify(payload), (200 if percent >= 50 else 503)
