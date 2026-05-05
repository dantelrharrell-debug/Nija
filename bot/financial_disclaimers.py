"""
NIJA Financial Disclaimers - App Store Compliance
==================================================

This module provides all financial disclaimers required for App Store approval.
Ensures compliance with financial regulations and App Store guidelines.

CRITICAL FOR APP STORE APPROVAL:
- Clear risk disclaimers
- No guaranteed profit claims
- Transparent about losses
- User must acknowledge risks
"""

import logging

logger = logging.getLogger("nija.disclaimers")


# Main risk disclaimer - shown on startup
RISK_DISCLAIMER = """
╔════════════════════════════════════════════════════════════════════╗
║                     ⚠️  IMPORTANT RISK DISCLOSURE  ⚠️                ║
╚════════════════════════════════════════════════════════════════════╝

CRYPTOCURRENCY TRADING INVOLVES SUBSTANTIAL RISK OF LOSS

⚠️  YOU CAN LOSE MONEY:
   • Cryptocurrency markets are highly volatile
   • Past performance does NOT indicate future results
   • You can lose some or ALL of your invested capital
   • Only trade with money you can afford to lose

🤖 ABOUT THIS SOFTWARE:
   • NIJA is an independent trading tool - NOT investment advice
   • You make all decisions about when and what to trade
   • This software executes trades based on YOUR configuration
   • System optimizations are technical in nature and do not imply improved financial outcomes.
   • NO GUARANTEES of profit or performance are made

📊 INDEPENDENT TRADING MODEL:
   • Each account trades independently using the same strategy framework
   • Account-specific state (PnL, exposure, cooldowns) shapes every decision
   • No copy trading or signal distribution to other users
   • Each user controls their own trading strategy and risk
   • Your results are based on YOUR account's performance

🛡️  YOUR RESPONSIBILITY:
   • You are solely responsible for your trading decisions
   • You control when trading is enabled or disabled
   • You set your own risk parameters and position sizes
   • Consult a licensed financial advisor before trading

By using this software, you acknowledge that you understand and accept
these risks. NIJA and its developers are not liable for any trading losses.

═══════════════════════════════════════════════════════════════════════
"""


# Short disclaimer for logs
SHORT_DISCLAIMER = """
⚠️  RISK WARNING: Trading involves substantial risk of loss.
   Past performance does not indicate future results.
   Only trade with money you can afford to lose.
"""


# Independent trading model explanation
INDEPENDENT_TRADING_EXPLANATION = """
╔════════════════════════════════════════════════════════════════════╗
║              📊 INDEPENDENT TRADING MODEL EXPLAINED 📊              ║
╚════════════════════════════════════════════════════════════════════╝

WHAT IS INDEPENDENT TRADING?

✅ EACH account trades INDEPENDENTLY:
   • Your account evaluates market conditions independently
   • Your trades are based on YOUR account's algorithmic analysis
   • NO copying of trades from other users
   • NO master account controlling your trades
   • NO signal distribution or coordination between accounts

🔒 COMPLETE ISOLATION:
   • Your profits/losses are YOUR OWN
   • Other users' performance does NOT affect you
   • Each account has its own risk management
   • Each account makes its own trading decisions

🤖 HOW IT WORKS:
   • All accounts use the same strategy framework with account-specific state
   • Per-account risk scaling, timing jitter, and cooldown variance are enforced
   • Market conditions may trigger similar trades across accounts
   • But each account's execution context is INDEPENDENT

💡 THINK OF IT LIKE:
   • Multiple people using the same weather app
   • They all see the same forecast (algorithm)
   • But each person decides independently what to do about it
   • No one is copying anyone else's decisions

═══════════════════════════════════════════════════════════════════════
"""


# Trading mode explanation
TRADING_MODE_EXPLANATION = """
╔════════════════════════════════════════════════════════════════════╗
║                    🔧 TRADING MODES EXPLAINED 🔧                     ║
╚════════════════════════════════════════════════════════════════════╝

NIJA SUPPORTS MULTIPLE TRADING MODES:

🔴 DISABLED MODE (Default - Safest):
   • NO credentials configured
   • NO trading possible
   • App starts in this mode for safety
   • Perfect for: First installation, testing setup

📊 MONITOR MODE:
   • Credentials configured but LIVE_CAPITAL_VERIFIED=false
   • Connects to exchanges and shows market data
   • NO trades are executed (safety lock enabled)
   • Perfect for: Watching markets, testing connection

🎭 DRY-RUN MODE:
   • Simulated trading - NO real money
   • Shows what trades WOULD be executed
   • For testing and App Store review
   • Enable: Set DRY_RUN_MODE=true
   • Perfect for: Testing strategy, demonstrations

💓 HEARTBEAT MODE:
   • Executes ONE tiny test trade
   • Verifies API connectivity and trading works
   • Bot auto-disables after trade completes
   • Enable: Set HEARTBEAT_TRADE=true
   • Perfect for: Deployment verification

🟢 LIVE TRADING MODE:
   • REAL MONEY trading enabled
   • Requires: Credentials + LIVE_CAPITAL_VERIFIED=true
   • Your capital is at risk
   • Perfect for: Actual trading after testing

⚠️  IMPORTANT: You control which mode to use
   Change modes in your environment configuration (.env file)

═══════════════════════════════════════════════════════════════════════
"""


def display_startup_disclaimers():
    """
    Display all required disclaimers on startup.
    
    This function should be called BEFORE any trading begins.
    Ensures users are fully informed of risks.
    """
    logger.info("")
    logger.info(RISK_DISCLAIMER)
    logger.info("")
    logger.info(INDEPENDENT_TRADING_EXPLANATION)
    logger.info("")
    logger.info(TRADING_MODE_EXPLANATION)
    logger.info("")
    

def display_risk_warning():
    """Display short risk warning (for periodic reminders)"""
    logger.warning(SHORT_DISCLAIMER)


def get_user_acknowledgment_text() -> str:
    """
    Get text for user to acknowledge before enabling live trading.
    
    Returns:
        str: Acknowledgment text that user must confirm
    """
    return """
I acknowledge that:
1. Cryptocurrency trading involves substantial risk of loss
2. I can lose some or all of my invested capital
3. Past performance does not indicate future results
4. NIJA provides no guarantees of profit
5. I am solely responsible for my trading decisions
6. I have consulted a financial advisor or understand the risks
7. I am trading with money I can afford to lose

To enable live trading, set LIVE_CAPITAL_VERIFIED=true in your .env file.
This confirms you understand and accept these risks.
"""


def log_compliance_notice():
    """Log compliance information for audit trail"""
    logger.info("=" * 70)
    logger.info("📜 FINANCIAL COMPLIANCE NOTICE")
    logger.info("=" * 70)
    logger.info("   • NIJA is a trading tool, NOT a financial advisor")
    logger.info("   • No investment advice is provided")
    logger.info("   • Technical optimizations do not imply improved financial outcomes")
    logger.info("   • No guaranteed returns or performance claims")
    logger.info("   • Independent trading model (no copy trading)")
    logger.info("   • User controls all trading decisions")
    logger.info("   • User bears all risk of trading losses")
    logger.info("=" * 70)
