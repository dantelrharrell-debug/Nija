"""
NIJA ULTIMATE TRADING LOGIC™ - CROSS-MARKET EDITION
====================================================

"One logic. Multiple markets. Auto-adaptive."

Built for ultra-clean entries across ALL asset classes:
- Crypto (Spot + Futures + Coinbase)
- Stocks (Intraday Trading)
- Futures (Indexes: S&P, NASDAQ, Dow, Gold, Oil)
- Options (Day trading contracts)

This file documents all exact values used by the NIJA trading system.
"""

# ═══════════════════════════════════════════════════════════════════
# ✅ 1. CORE PARAMETERS (UNIVERSAL - All Markets)
# ═══════════════════════════════════════════════════════════════════

UNIVERSAL_INDICATORS = {
    "vwap": {
        "type": "session",
        "description": "Main Trend Filter - ONLY LONG above VWAP, ONLY SHORT below VWAP"
    },
    "rsi": {
        "period": 14,
        "description": "Momentum Trigger - Use RSI CROSS detection"
    },
    "ema": {
        "periods": [9, 21, 50],
        "description": "Precision Entry Timing",
        "alignment_long": "EMA 9 > EMA 21 > EMA 50",
        "alignment_short": "EMA 9 < EMA 21 < EMA 50"
    },
    "volume_filter": "Current candle ≥ last 2 candles combined",
    "timeframes": {
        "primary": "1m (entries)",
        "confirmation": "5m (confirmation)"
    }
}

# ═══════════════════════════════════════════════════════════════════
# ⚡ 2. MARKET-SPECIFIC ADAPTATION RULES
# ═══════════════════════════════════════════════════════════════════

MARKET_PARAMETERS = {
    "CRYPTO": {
        "description": "Crypto = fastest + most volatile",
        "stop_loss": "0.35-0.50%",
        "targets": {
            "tp1": "0.5%",
            "tp2": "1.0%",
            "tp3": "1.5-2.0%"
        },
        "trailing": {
            "ema_21": True,
            "percentage": "0.25% → 0.15% → 0.10%"
        },
        "position_size": {
            "conservative": "2%",
            "standard": "5%",
            "a_plus": "10%"
        },
        "max_daily_trades": 15
    },

    "STOCKS": {
        "description": "Stocks are slower, lower volatility",
        "stop_loss": "0.15-0.30%",
        "targets": {
            "tp1": "0.25%",
            "tp2": "0.50%",
            "tp3": "0.75-1.0%"
        },
        "trailing": {
            "ema_21": True,
            "percentage": "Active above +0.75% profit"
        },
        "position_size": {
            "min": "1%",
            "max": "5%",
            "note": "No single stock trade > 5% of equity"
        },
        "max_daily_trades": 10
    },

    "FUTURES": {
        "description": "Futures move violently - throttle risk",
        "stop_loss": {
            "type": "Tick-based (auto-convert)",
            "ES": "0.15-0.25%",
            "NQ": "0.25-0.40%",
            "GOLD": "0.30-0.50%"
        },
        "targets": {
            "tp1": "0.25%",
            "tp2": "0.50%",
            "tp3": "0.75-1.0%"
        },
        "trailing": {
            "ema_21": "Momentum trailing only",
            "percentage": "No percentage trail until +0.5% profit"
        },
        "position_size": {
            "max_risk": "0.75% of account per futures trade"
        },
        "max_daily_trades": 7
    },

    "OPTIONS": {
        "description": "Options require combo filters to avoid fake moves",
        "entry_filters": {
            "delta": "≥ 0.30",
            "bid_ask_spread": "< 8%",
            "volume": "> 500 contracts",
            "iv_rank": "< 50"
        },
        "stop_loss": "10-20% of premium",
        "targets": {
            "tp1": "15%",
            "tp2": "25%",
            "tp3": "40-50%"
        },
        "trailing": {
            "ema_21": "Trail by underlying EMA-21",
            "premium": "5-10% behind current price"
        },
        "position_size": {
            "max": "3% of account per options trade",
            "overnight": "No overnight holding"
        },
        "max_daily_trades": 5
    }
}

# ═══════════════════════════════════════════════════════════════════
# 🔥 3. UNIVERSAL ENTRY RULES (ALL MARKETS)
# ═══════════════════════════════════════════════════════════════════

LONG_ENTRY = {
    "description": "All conditions must be TRUE for MARKET BUY",
    "conditions": [
        "1. Price ABOVE VWAP",
        "2. EMA 9 > EMA 21 > EMA 50",
        "3. RSI crossing up",
        "4. Volume spike (≥ prev 2 candles)",
        "5. Bullish candle close"
    ],
    "action": "Execute MARKET BUY"
}

SHORT_ENTRY = {
    "description": "All conditions must be TRUE for SHORT/PUT",
    "conditions": [
        "1. Price BELOW VWAP",
        "2. EMA 9 < EMA 21 < EMA 50",
        "3. RSI crossing down",
        "4. Volume spike (≥ prev 2 candles)",
        "5. Bearish candle close"
    ],
    "action": {
        "if_shorting_supported": "Execute MARKET SELL/SHORT",
        "if_options": "Buy PUT",
        "if_crypto_spot_only": "Skip trade (no short)"
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
# � POSITION SIZING (NIJA SPECIFICATION)
# ═══════════════════════════════════════════════════════════════════

POSITION_SIZING = {
    "minimum": "2% of account equity",
    "maximum": "10% of account equity",
    "default": "3-7% depending on signal strength",

    "signal_based_allocation": {
        "score_5": {
            "range": "8-10%",
            "description": "All 5 conditions strong (A+ setup)",
            "default": 9.0
        },
        "score_4": {
            "range": "5-7%",
            "description": "4 conditions met (good setup)",
            "default": 6.0
        },
        "score_3": {
            "range": "3-4%",
            "description": "3 conditions met (decent setup)",
            "default": 3.5
        },
        "score_2_or_less": {
            "range": "0% or 2%",
            "description": "Conditions barely align - no trade or minimum",
            "default": 0.0
        }
    }
}

# ═══════════════════════════════════════════════════════════════════
# 🧠 6. COOL DOWNS & SAFETY LOCKS (ALL MARKETS)
# ═══════════════════════════════════════════════════════════════════

SAFETY_LOCKS = {
    "news_cooldown": {
        "duration": "3 minutes",
        "description": "No trading first 3 minutes after major news"
    },
    "extreme_iv": {
        "description": "No trading during extreme IV spikes (options)",
        "threshold": "IV Rank > 80"
    },
    "max_daily_loss": {
        "all_markets": "2.5% of account",
        "description": "Universal safety limit"
    },
    "max_daily_trades_by_market": {
        "crypto": 15,
        "stocks": 10,
        "futures": 7,
        "options": 5
    }
}

# ═══════════════════════════════════════════════════════════════════
# ⚖️ 5. MARKET-AWARE POSITION SIZING (DYNAMIC)
# ═══════════════════════════════════════════════════════════════════

POSITION_SIZING_TABLE = {
    "CRYPTO": {"min": "2%", "max": "10%"},
    "STOCKS": {"min": "1%", "max": "5%"},
    "FUTURES": {"min": "0.25%", "max": "0.75%"},
    "OPTIONS": {"min": "1%", "max": "3%"}
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
# 📝 NIJA ULTIMATE TRADING LOGIC SUMMARY
# ═══════════════════════════════════════════════════════════════════

NIJA_PHILOSOPHY = """
NIJA ULTIMATE TRADING LOGIC™ - CROSS-MARKET EDITION
"One logic. Multiple markets. Auto-adaptive."

Built for ultra-clean entries across ALL asset classes:
✅ Crypto (Spot + Futures + Coinbase)
✅ Stocks (Intraday Trading)
✅ Futures (ES, NQ, YM, GC, CL, etc.)
✅ Options (Day trading contracts)

CORE PRINCIPLES (UNIVERSAL):
1. VWAP = Main trend filter (prevents counter-trend FOMO)
2. RSI CROSS = Momentum trigger (not just levels)
3. EMA Alignment = Precision entry timing (9 > 21 > 50)
4. Volume Confirmation = Real buying/selling pressure
5. Candle Close = Confirmation (no mid-candle entries)

AUTO-DETECTION:
- Bot auto-detects market type from symbol
- Adjusts risk/volatility parameters automatically
- Crypto: BTC-USD, ETH-USD, SOL-USD
- Stocks: AAPL, TSLA, SPY
- Futures: ES, NQ, GC, CL
- Options: Contract symbols with strikes

POSITION MANAGEMENT (MARKET-ADAPTIVE):
- Crypto: 2-10% per trade
- Stocks: 1-5% per trade
- Futures: 0.25-0.75% per trade
- Options: 1-3% per trade
- Score-based allocation (5-point system)
- TP Ladder: 50% → 25% → 25%
- Dynamic stop-loss (market-specific)
- EMA-21 + percentage trailing

RISK CONTROLS (UNIVERSAL):
- Max daily loss: 2.5% (all markets)
- Trade cooldown: 2 minutes
- Smart burn-down: 3 losses → 2% for 3 trades
- Daily profit lock: +3% → A+ only, reduced size
- No-trade zones: Extreme RSI, low volume, large wicks
- News cooldown: 3 minutes after major events

MAX DAILY TRADES BY MARKET:
- Crypto: 15 trades/day
- Stocks: 10 trades/day
- Futures: 7 trades/day
- Options: 5 trades/day

ENTRY REQUIREMENTS (ALL MUST BE TRUE):
LONG: Price > VWAP + EMA 9>21>50 + RSI cross up + Volume + Bullish close
SHORT: Price < VWAP + EMA 9<21<50 + RSI cross down + Volume + Bearish close

SHORTING LOGIC:
- If asset supports shorting → Execute SHORT
- If options → Buy PUT
- If crypto spot only → Skip trade (no short)

OPTIONS-SPECIFIC FILTERS:
- Delta ≥ 0.30
- Bid/ask spread < 8%
- Volume > 500 contracts
- IV Rank < 50
- No overnight holding

This is the master blueprint the NIJA Bot follows across all markets.
"""
