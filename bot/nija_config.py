"""
NIJA TRADING BOT - EXACT DEFAULT PARAMETERS
===========================================

This file documents all exact values used by the NIJA trading system.
These parameters are hardcoded into the bot logic.
"""

# ═══════════════════════════════════════════════════════════════════
# 📊 CHART TIMEFRAMES
# ═══════════════════════════════════════════════════════════════════

TIMEFRAMES = {
    "primary": "1m",      # Primary chart for entries
    "confirmation": "5m"  # Confirmation chart for validation
}

# Note: Current implementation uses 5m as primary
# To use 1m, update get_product_candles(granularity=60) in trading_strategy.py

# ═══════════════════════════════════════════════════════════════════
# 📈 INDICATORS
# ═══════════════════════════════════════════════════════════════════

INDICATORS = {
    "vwap": {
        "type": "session",  # Session-based VWAP
        "description": "Volume-Weighted Average Price"
    },
    "rsi": {
        "period": 14,
        "description": "Relative Strength Index"
    },
    "ema": {
        "periods": [9, 21, 50],
        "description": "Exponential Moving Averages"
    },
    "macd": {
        "fast": 12,
        "slow": 26,
        "signal": 9,
        "description": "Moving Average Convergence Divergence"
    }
}

# ═══════════════════════════════════════════════════════════════════
# ✅ ENTRY FILTERS
# ═══════════════════════════════════════════════════════════════════

ENTRY_FILTERS = {
    "min_volume": {
        "rule": "previous_2_candles",
        "description": "Volume must exceed previous 2 candles average"
    },
    "rsi_cross": {
        "rule": "cross_only",
        "description": "RSI must cross level, not just be at level"
    },
    "candle_close": {
        "rule": "must_close",
        "description": "Wait for candle to close before entry"
    }
}

# ═══════════════════════════════════════════════════════════════════
# 🛡️ RISK PARAMETERS
# ═══════════════════════════════════════════════════════════════════

RISK = {
    "stop_loss_pct": {
        "min": 0.35,  # 0.35%
        "max": 0.50,  # 0.50%
        "description": "Base stop-loss range (volatility-adjusted)"
    },
    "max_daily_loss_pct": 2.5,  # 2.5% of account
    "max_daily_trades": 15,
    "max_exposure_pct": 30.0,  # 30% max total exposure
}

# ═══════════════════════════════════════════════════════════════════
# 🎯 TAKE-PROFIT TARGETS
# ═══════════════════════════════════════════════════════════════════

TARGETS = {
    "tp1": {
        "profit_pct": 0.5,   # +0.5%
        "close_size": 0.50,  # Close 50%
        "action": "Activate TSL"
    },
    "tp2": {
        "profit_pct": 1.0,   # +1.0%
        "close_size": 0.25,  # Close 25%
        "action": "Activate TTP"
    },
    "tp3": {
        "profit_pct_min": 1.5,  # +1.5%
        "profit_pct_max": 2.0,  # +2.0%
        "close_size": 0.25,     # Close final 25%
        "action": "Final exit or trail"
    }
}

# ═══════════════════════════════════════════════════════════════════
# 💰 CAPITAL ALLOCATION (Signal Scoring)
# ═══════════════════════════════════════════════════════════════════

ALLOCATION = {
    "score_5": {
        "min_pct": 8.0,
        "max_pct": 10.0,
        "default": 9.0,
        "description": "A+ setup - Full allocation"
    },
    "score_4": {
        "min_pct": 4.0,
        "max_pct": 6.0,
        "default": 5.0,
        "description": "Good setup - Medium allocation"
    },
    "score_3": {
        "min_pct": 2.0,
        "max_pct": 3.0,
        "default": 2.5,
        "description": "Decent setup - Small allocation"
    },
    "score_2_or_less": {
        "allocation": 0.0,
        "description": "No trade"
    }
}

# ═══════════════════════════════════════════════════════════════════
# 🚦 TRADE COOLDOWN
# ═══════════════════════════════════════════════════════════════════

COOLDOWN = {
    "seconds": 120,  # 2 minutes
    "description": "Prevents back-to-back candle chasing and revenge trading"
}

# ═══════════════════════════════════════════════════════════════════
# ❌ NO-TRADE ZONES
# ═══════════════════════════════════════════════════════════════════

NO_TRADE_ZONES = {
    "extreme_rsi": {
        "high": 90,
        "low": 10,
        "description": "1m chart extreme RSI levels"
    },
    "low_volume": {
        "threshold": 0.3,  # 30% of average volume
        "description": "Low-volume consolidation"
    },
    "large_wicks": {
        "wick_to_body_ratio": 2.0,
        "description": "Wick > 2x body size"
    },
    "news_events": {
        "cooldown_minutes": 3,
        "description": "First 3 minutes after major news (manual check)"
    }
}

# ═══════════════════════════════════════════════════════════════════
# 🔥 SMART BURN-DOWN RULE
# ═══════════════════════════════════════════════════════════════════

BURN_DOWN = {
    "trigger": {
        "consecutive_losses": 3,
        "description": "Activate after 3 losses in a row"
    },
    "action": {
        "allocation_pct": 2.0,  # Reduce to 2%
        "trade_count": 3,       # For next 3 trades
        "description": "Auto-reduce allocation"
    },
    "recovery": {
        "condition": "3 wins in burn-down mode",
        "action": "Resume normal allocation"
    }
}

# ═══════════════════════════════════════════════════════════════════
# 🔒 DAILY PROFIT LOCK
# ═══════════════════════════════════════════════════════════════════

PROFIT_LOCK = {
    "trigger": {
        "daily_profit_pct": 3.0,  # +3% daily profit
        "description": "Activate profit protection mode"
    },
    "action": {
        "min_signal_score": 5,     # Only A+ setups
        "max_allocation_pct": 2.5,  # Cap at 2-3%
        "description": "Smaller size, only best setups"
    }
}

# ═══════════════════════════════════════════════════════════════════
# 📊 SIGNAL SCORING CRITERIA (1-5 points)
# ═══════════════════════════════════════════════════════════════════

SIGNAL_SCORING = {
    "buy_criteria": [
        "+1 point: Price above VWAP",
        "+1 point: RSI oversold cross (30-50 range)",
        "+1 point: Volume > 1.2x average",
        "+1 point: MACD bullish crossover",
        "+1 point: EMA alignment (9 > 21)"
    ],
    "sell_criteria": [
        "+1 point: Price below VWAP",
        "+1 point: RSI overbought cross (50-70 range)",
        "+1 point: Volume > 1.2x average",
        "+1 point: MACD bearish crossunder",
        "+1 point: EMA alignment (9 < 21)"
    ]
}

# ═══════════════════════════════════════════════════════════════════
# 🎯 TRADING PAIRS
# ═══════════════════════════════════════════════════════════════════

TRADING_PAIRS = ["BTC-USD", "ETH-USD", "SOL-USD"]

# ═══════════════════════════════════════════════════════════════════
# ⏱️ BOT EXECUTION
# ═══════════════════════════════════════════════════════════════════

EXECUTION = {
    "cycle_interval_seconds": 300,  # 5 minutes
    "order_type": "market",
    "min_trade_size_usd": 10.0
}

# ═══════════════════════════════════════════════════════════════════
# 📝 NOTES
# ═══════════════════════════════════════════════════════════════════

NOTES = """
NIJA BEHAVIOR:
- Dynamic stop-loss: 0.35-0.50% (volatility-adjusted)
- Partial closes: 50% → 25% → 25%
- TSL activates at TP1 (+0.5%)
- TTP activates at TP2 (+1.0%)
- EMA-21 trail + percentage micro-trail (0.25% → 0.15% → 0.10%)
- Score-based allocation: 2-10%
- 2-minute trade cooldown
- Smart burn-down after 3 losses
- Daily profit lock at +3%
- Max 2.5% daily loss
- Max 15 daily trades
- No-trade zones enforced
"""
