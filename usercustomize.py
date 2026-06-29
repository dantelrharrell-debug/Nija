"""User-level startup defaults for NIJA runtime."""

import os

# US OKX accounts require the US regional API host. Keep an explicit Railway
# OKX_BASE_URL override if one is provided; otherwise default to us.okx.com.
os.environ.setdefault("OKX_BASE_URL", "https://us.okx.com")
os.environ.setdefault("OKX_US_REGION", "true")

# Conservative execution defaults: NIJA cannot guarantee profit, but it should
# require fee/slippage-aware positive expectancy before entry orders are allowed.
os.environ.setdefault("NIJA_PROFITABILITY_GUARD_ENABLED", "true")
os.environ.setdefault("NIJA_MIN_EXPECTANCY_THRESHOLD_PCT", "0.15")
os.environ.setdefault("MIN_EXPECTANCY_THRESHOLD_PCT", "0.15")
os.environ.setdefault("NIJA_MIN_EDGE_THRESHOLD", "0.0015")
os.environ.setdefault("MIN_EDGE_THRESHOLD", "0.0015")
os.environ.setdefault("NIJA_LOG_TRADE_DECISIONS", "true")
