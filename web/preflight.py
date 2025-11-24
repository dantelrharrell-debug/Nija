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
        # try internal clients too
        import importlib
        ok = False
        for name in ("coinbase_advanced_py.client", "coinbase_advanced.client", "nija_coinbase_client", "nija_client"):
            try:
                importlib.import_module(name)
                ok = True
                break
            except Exception:
                continue
        return {"ok": ok, "detail": "coinbase import present" if ok else "none found"}
    except Exception as e:
        return {"ok": False, "detail": repr(e)}

def compute_score(results, weights=None):
    default = {
        "env": 10,
        "imports": 10,
        "blueprint": 20,
        "health": 10,
        "auth": 25,
        "accounts": 25
    }
    if weights is None:
        weights = default
    total = sum(weights.values())
    score = 0.0
    for k,w in weights.items():
        if results.get(k, {}).get("ok"):
            score += w
    return round((score/total)*100, 1) if total else 0.0

@bp.route("/preflight", methods=["GET"])
def preflight():
    results = {}
    results["env"] = check_env()
    results["imports"] = check_imports()
    # blueprint present?
    try:
        bp_names = [b.name for b in current_app.blueprints.values()]
        results["blueprint"] = {"ok": "tradingview" in bp_names or "preflight" in bp_names, "detail": bp_names}
    except Exception as e:
        results["blueprint"] = {"ok": False, "detail": repr(e)}
    # health present?
    try:
        has_health = any("health" in rule.rule for rule in current_app.url_map.iter_rules())
        results["health"] = {"ok": has_health, "detail": [r.rule for r in current_app.url_map.iter_rules() if "/health" in r.rule]}
    except Exception as e:
        results["health"] = {"ok": False, "detail": repr(e)}
    # skip expensive auth/accounts here (optional)
    results["auth"] = {"ok": False, "detail": "skipped by preflight (requires credentials)"}
    results["accounts"] = {"ok": False, "detail": "skipped by preflight (requires credentials)"}
    percent = compute_score(results)
    return jsonify({"ok": percent >= 80, "percent": percent, "results": results}), (200 if percent >= 50 else 503)
