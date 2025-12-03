#!/usr/bin/env python3
# Drop into project root and run: python3 nija_strategy_status.py
# Serves /strategy/status on 0.0.0.0:8081 and prints repo/env findings (safe: does not print secrets).

import os, json, re, subprocess
from pathlib import Path
from flask import Flask, jsonify

ROOT = Path(".").resolve()
app = Flask("nija-strategy-status")

KEYWORDS = [
  r"\bVWAP\b", r"\bvwap\b", r"\bRSI\b", r"\brsi\b",
  r"tradingview_ta", r"TradingView_TA", r"crossover", r"crossed",
  r"compute_vwap", r"submit_order", r"/webhook", r"size_pct", r"order_type"
]

def find_files_with_keywords():
    hits = {}
    for p in ROOT.rglob("*"):
        try:
            if p.is_file() and p.suffix.lower() in {'.py','.js','.ts','.json','.yml','.yaml','.env','.ini','.md'}:
                txt = p.read_text(errors='ignore')
                for kw in KEYWORDS:
                    if re.search(kw, txt, re.I):
                        hits.setdefault(str(p.relative_to(ROOT)), []).append(kw)
        except Exception:
            continue
    return hits

def read_common_configs():
    configs = {}
    for name in [".env","config.json","strategy.json","config.yml","strategy.yml","settings.yml"]:
        p = ROOT / name
        if p.exists():
            try:
                txt = p.read_text()
                if p.name == ".env":
                    lines = []
                    for line in txt.splitlines():
                        if "=" in line:
                            k,_ = line.split("=",1)
                            lines.append(f"{k}=<REDACTED>")
                        else:
                            lines.append(line)
                    configs[name] = "\n".join(lines)
                else:
                    configs[name] = txt[:5000]
            except:
                configs[name] = "<unreadable>"
    return configs

def pip_list():
    try:
        out = subprocess.check_output(["pip","freeze"], stderr=subprocess.DEVNULL, text=True)
        return [line.strip() for line in out.splitlines() if line.strip()]
    except Exception:
        return []

@app.route("/strategy/status")
def status():
    hits = find_files_with_keywords()
    configs = read_common_configs()
    pkgs = pip_list()
    env_keys = ["LIVE_TRADING","VWAP","RSI","SIZE_PCT","ORDER_TYPE","WEBHOOK","TRADINGVIEW"]
    env = {k: ("<SET>" if k in os.environ else "<NOT_SET>") for k in env_keys}
    return jsonify({
        "repo_hits_count": len(hits),
        "sample_files_with_hits": list(hits.keys())[:40],
        "configs_found": configs,
        "installed_packages_sample": [p for p in pkgs if any(x in p.lower() for x in ["tradingview","coinbase","vwap","rsi","advanced"])][:40],
        "env_summary": env
    })

if __name__ == "__main__":
    print("Serving on http://0.0.0.0:8081/strategy/status")
    app.run(host="0.0.0.0", port=8081)
