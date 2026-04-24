"""
NIJA READY-TO-DEPLOY CONFIGURATION
====================================

Full production deployment config for NIJA autonomous trading bot.
Implements the "Immediate Action" checklist:

  ✅ Widen grid ranges / enable market fallback
  ✅ Reduce EMA periods for trend strategy (20/50 → 10/30)
  ✅ Loosen RSI / Bollinger thresholds for mean reversion
  ✅ Confirm threads are live and set to trade (not simulation)
  ✅ Stabilize API connections (last-known-balance fallback with reduced size)
  ✅ Capital allocations with ≥10% per active pair

Usage
-----
Import the DEPLOY_CONFIG dict into your strategy bootstrap or set the
environment variables listed below before starting NIJA.

All secrets (API keys, PEM content) must be supplied via environment
variables — never hardcode them.
"""

import os

# ═══════════════════════════════════════════════════════════════════
# 🧵 THREAD ASSIGNMENTS
# Each strategy runs on its own dedicated thread.
# ═══════════════════════════════════════════════════════════════════

THREAD_CONFIG = {
    # Thread 1 — Market Scanner (runs every scan_interval_seconds)
    "market_scanner": {
        "enabled": True,
        "thread_name": "nija-scanner",
        "scan_interval_seconds": 150,  # 2.5 minutes (was 5 min) for faster signal detection
        "live_mode": True,             # ✅ Live trading (not simulation)
        "pairs": [
            "BTC-USD", "ETH-USD", "SOL-USD",
            "MATIC-USD", "ADA-USD", "AVAX-USD", "LINK-USD", "DOT-USD",
        ],
    },

    # Thread 2 — Trend-Following Strategy
    "trend_following": {
        "enabled": True,
        "thread_name": "nija-trend",
        "live_mode": True,
        "ema_fast": 10,    # Reduced from 20 for faster trend detection
        "ema_slow": 30,    # Reduced from 50 for faster trend detection
        "min_capital_pct_per_pair": 0.10,  # ≥10% capital allocated per pair
        "max_capital_pct_per_pair": 0.25,
        "pairs": ["BTC-USD", "ETH-USD", "SOL-USD", "AVAX-USD"],
    },

    # Thread 3 — Mean Reversion Strategy
    "mean_reversion": {
        "enabled": True,
        "thread_name": "nija-mean-rev",
        "live_mode": True,
        "rsi_oversold": 35,    # Widened from 30 for more entry opportunities
        "rsi_overbought": 65,  # Widened from 70 for more entry opportunities
        "bb_period": 20,
        "bb_std_dev": 1.5,     # Reduced from 2.0 for tighter bands (more signals)
        "pairs": ["BTC-USD", "ETH-USD", "SOL-USD", "MATIC-USD", "ADA-USD", "LINK-USD", "DOT-USD"],
        "min_capital_pct_per_pair": 0.10,
        "max_capital_pct_per_pair": 0.20,
    },

    # Thread 4 — Grid / Limit Order Manager
    "grid_manager": {
        "enabled": True,
        "thread_name": "nija-grid",
        "live_mode": True,
        "grid_range_pct": 0.015,           # 1.5% (widened from 0.5-1%)
        "grid_levels": 18,                 # 18 levels (up from 10)
        "order_spacing_pct": 0.001,        # 0.1% between levels
        "market_fallback_enabled": True,
        "market_fallback_timeout_seconds": 300,  # 300 s = 5 min before switching to market orders
        "capital_allocation_pct": 0.30,    # 30% of free balance for grid orders
        "min_order_usd": 10.0,
        "pairs": ["BTC-USD", "ETH-USD", "SOL-USD"],
    },

    # Thread 5 — Position / Risk Monitor (watchdog)
    "risk_monitor": {
        "enabled": True,
        "thread_name": "nija-risk",
        "check_interval_seconds": 30,
        "live_mode": True,
    },

    # Thread 6 — TradingView Webhook Listener (instant execution)
    "webhook_listener": {
        "enabled": True,
        "thread_name": "nija-webhook",
        "live_mode": True,
        "port": int(os.getenv("PORT", "5000")),
    },
}

# ═══════════════════════════════════════════════════════════════════
# 💰 CAPITAL ALLOCATIONS
# Total must be ≤ 100%.  Remaining balance stays as cash reserve.
# ═══════════════════════════════════════════════════════════════════

CAPITAL_ALLOCATION = {
    # Strategy-level allocations (% of total portfolio)
    "trend_following":  0.35,   # 35% — trend strategy (EMA 10/30)
    "mean_reversion":   0.35,   # 35% — mean reversion (RSI 35/65, BB 1.5σ)
    "grid_orders":      0.20,   # 20% — grid / limit order book
    "cash_reserve":     0.10,   # 10% — kept liquid for fees and drawdown buffer

    # Per-pair minimum (enforced inside each strategy thread)
    "min_per_pair_pct": 0.10,   # 10% of strategy allocation per active pair
    "max_per_pair_pct": 0.25,   # 25% cap to avoid concentration risk

    # Rebalance trigger: rebalance when any strategy drifts > 10% from target
    "rebalance_threshold_pct": 0.10,
    "auto_rebalance": True,
}

# ═══════════════════════════════════════════════════════════════════
# 📡 CONNECTION & DATA SETTINGS
# ═══════════════════════════════════════════════════════════════════

CONNECTION_CONFIG = {
    # API rate-limiting and retry
    "api_retry_attempts": 5,
    "api_retry_delay_seconds": 2.0,    # Base delay; doubles on each retry (exponential backoff)
    "api_max_retry_delay_seconds": 30.0,

    # Watchdog: reconnect if no successful API call for this many seconds
    "watchdog_timeout_seconds": 60,
    "watchdog_reconnect_attempts": 3,

    # Fallback trading on last-known prices during brief disconnects
    "allow_last_known_price_trading": True,
    "last_known_price_max_age_seconds": 120,   # Stale prices rejected after 2 min
    "last_known_price_position_size_pct": 0.5, # Half position size when using stale prices

    # Connection pool settings (applied to Coinbase / Kraken HTTP sessions)
    "pool_connections": 10,
    "pool_maxsize": 20,
    "pool_retries": 3,
}

# ═══════════════════════════════════════════════════════════════════
# 📊 SIGNAL THRESHOLDS (ADJUSTED FOR IMMEDIATE ENTRY)
# ═══════════════════════════════════════════════════════════════════

SIGNAL_CONFIG = {
    # ── Trend-Following ────────────────────────────────────────────
    "trend": {
        "ema_fast": 10,    # Reduced from 20 → faster crossover detection
        "ema_slow": 30,    # Reduced from 50 → shorter trend horizon
        # Minimum score before entering a trend trade (3/5 is the "immediate entry" mode)
        "min_signal_score": 3,
        "min_capital_pct_per_pair": 0.10,
    },

    # ── Mean Reversion ─────────────────────────────────────────────
    "mean_reversion": {
        "rsi_oversold": 35,      # Widened from 30 (more entries in minor pullbacks)
        "rsi_overbought": 65,    # Widened from 70 (more entries on minor peaks)
        "bb_period": 20,
        "bb_std_dev": 1.5,       # Reduced from 2.0 (bands trigger on smaller moves)
        "min_signal_score": 2,   # Enter on weaker pullbacks while widening filters
    },

    # ── Grid / Limit Orders ────────────────────────────────────────
    "grid": {
        "range_pct": 0.015,                # 1.5% grid range (from 0.5-1%)
        "levels": 18,                      # 18 levels (from 10)
        "order_spacing_pct": 0.001,        # 0.1% spacing
        "market_fallback_enabled": True,
        "market_fallback_timeout_seconds": 300,  # 300 s = 5 min; matches GRID_CONFIG in apex_config.py
    },

    # ── General ───────────────────────────────────────────────────
    "min_confidence": 0.55,   # Slightly lower to generate more immediate trades (was 0.60)
    "require_volume_confirmation": True,
    "volume_multiplier": 1.2,  # Volume must be 1.2× average
}

# ═══════════════════════════════════════════════════════════════════
# 🛡️ RISK LIMITS
# ═══════════════════════════════════════════════════════════════════

RISK_CONFIG = {
    # Position sizing — moderate/aggressive live settings
    "base_position_size_pct": 0.08,   # 8% of balance per trade (moderate/aggressive)
    "max_position_size_pct": 0.20,    # Hard cap at 20%
    "min_position_size_usd": 10.0,    # Exchange minimum

    # Stop-loss — widened for moderate/aggressive mode (room to breathe)
    "stop_loss_pct": 0.020,           # 2.0% stop-loss per trade (was 1.2%)
    "atr_stop_multiplier": 1.8,       # Alternative: 1.8× ATR below entry (was 1.5×)

    # Drawdown circuit-breakers — loosened for moderate/aggressive mode
    "max_daily_loss_pct": 0.05,       # Halt trading at -5% daily (was -2.5%)
    "max_drawdown_pct": 0.20,         # Halt trading at -20% drawdown from peak (was -12%)
    "drawdown_reduce_at_pct": 0.12,   # Cut position size by 50% at -12% drawdown (was -8%)

    # Consecutive-loss protection (smart burn-down)
    "consecutive_loss_limit": 4,
    "burn_down_position_pct": 0.04,   # Reduce to 4% for next 3 trades after losses (was 2%)
    "burn_down_trade_count": 3,

    # Daily profit lock
    "profit_lock_trigger_pct": 0.05,  # Lock profits after +5% daily (was +3%)
    "profit_lock_min_score": 4,       # Allow quality trades after profit lock (was 5)
    "profit_lock_max_size_pct": 0.04,

    # Exposure limits
    "max_total_exposure_pct": 0.80,   # Max 80% of balance in open positions (was 60%)
    "max_positions": 10,              # Max concurrent open positions (was 8)
    "max_positions_per_symbol": 1,

    # Trade frequency
    "max_trades_per_day": 30,
    "max_trades_per_hour": 12,
    "min_seconds_between_trades": 20,

    # Daily trade limits per market type
    "max_daily_trades_crypto": 30,
    "max_daily_trades_stocks": 10,   # Future: stocks support
    "max_daily_trades_futures": 7,   # Future: futures support
}

# ═══════════════════════════════════════════════════════════════════
# 🌐 MULTI-PAIR MONITORING
# ═══════════════════════════════════════════════════════════════════

MULTI_PAIR_CONFIG = {
    # Active pairs monitored across all strategies
    "active_pairs": [
        "BTC-USD",    # Bitcoin — primary liquidity
        "ETH-USD",    # Ethereum — primary alt
        "SOL-USD",    # Solana — high momentum
        "MATIC-USD",  # Polygon — mean-reversion candidate
        "ADA-USD",    # Cardano — mean-reversion candidate
        "AVAX-USD",   # Avalanche — trend-following candidate
        "LINK-USD",   # Chainlink — mean-reversion candidate
        "DOT-USD",    # Polkadot — mean-reversion candidate
    ],
    # High-priority pairs (get larger allocation within each strategy)
    "priority_pairs": ["BTC-USD", "ETH-USD", "SOL-USD"],
    # Pairs eligible for trend-following (higher liquidity required)
    "trend_pairs": ["BTC-USD", "ETH-USD", "SOL-USD", "AVAX-USD"],
    # Pairs eligible for mean-reversion
    "mean_reversion_pairs": [
        "BTC-USD", "ETH-USD", "SOL-USD",
        "MATIC-USD", "ADA-USD", "LINK-USD", "DOT-USD",
    ],
}

# ═══════════════════════════════════════════════════════════════════
# 🔗 BROKER / EXCHANGE SETTINGS
# ═══════════════════════════════════════════════════════════════════

BROKER_DEPLOY_CONFIG = {
    "primary_broker": "coinbase",
    "live_trading": True,       # ✅ Confirms live mode (not simulation)
    "paper_trading": False,     # ✅ Paper mode disabled

    "coinbase": {
        "enabled": True,
        # Credentials loaded from environment variables (never hardcode)
        "api_key_env": "COINBASE_API_KEY",
        "api_secret_env": "COINBASE_API_SECRET",
        "pem_content_env": "COINBASE_PEM_CONTENT",
    },

    # (Optional) Second broker for funding-rate arbitrage
    # Uncomment and set env vars to activate Binance or OKX
    # "binance": {
    #     "enabled": False,
    #     "api_key_env": "BINANCE_API_KEY",
    #     "api_secret_env": "BINANCE_API_SECRET",
    #     "product_type": "FUTURES",  # Required for funding-rate arb
    #     "capital_pct": 0.10,        # 10% of portfolio for delta-neutral hedge
    # },
    # "okx": {
    #     "enabled": False,
    #     "api_key_env": "OKX_API_KEY",
    #     "api_secret_env": "OKX_API_SECRET",
    #     "product_type": "FUTURES",
    #     "capital_pct": 0.10,
    # },
}

# ═══════════════════════════════════════════════════════════════════
# 📋 FULL DEPLOY CONFIG (consolidated view)
# ═══════════════════════════════════════════════════════════════════

DEPLOY_CONFIG = {
    "version": "1.0.0",
    "description": "NIJA Ready-to-Deploy Configuration — Immediate Trading Mode",
    "live_mode": True,
    "threads": THREAD_CONFIG,
    "capital": CAPITAL_ALLOCATION,
    "connection": CONNECTION_CONFIG,
    "signals": SIGNAL_CONFIG,
    "risk": RISK_CONFIG,
    "pairs": MULTI_PAIR_CONFIG,
    "brokers": BROKER_DEPLOY_CONFIG,
}
