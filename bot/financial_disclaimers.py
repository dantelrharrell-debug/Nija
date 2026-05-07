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
PRIMARY_DISCLOSURE_SECTIONS = [
    "A. Risk Disclosure",
    "Trading involves substantial risk of loss.",
    "YOU CAN LOSE MONEY.",
    "NO GUARANTEES of profitability or performance.",
    "Users are solely responsible for trading outcomes.",
    "",
    "B. Platform Classification",
    "NIJA is a software trading tool, NOT investment advice and not a financial advisor.",
    "No investment advice is provided.",
    "No copy trading or signal distribution occurs.",
    "",
    "C. Operational Model",
    "Each account operates independently using shared software logic with independent per-account evaluation,",
    "with account-specific state, exposure, cooldowns, and execution context. That’s it.",
]

RISK_DISCLAIMER = "\n".join(PRIMARY_DISCLOSURE_SECTIONS)


# Short disclaimer for logs
SHORT_DISCLAIMER = (
    "⚠️  RISK WARNING: Trading involves substantial risk of loss. "
    "YOU CAN LOSE MONEY. NO GUARANTEES of profitability or performance."
)


INDEPENDENT_TRADING_EXPLANATION = """
INDEPENDENT TRADING MODEL:
• Each account operates independently using shared software logic with independent per-account evaluation
• Account-specific state, exposure, cooldowns, and execution context shape decisions
• No copy trading or signal distribution occurs
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
   • ZERO capital exposure
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
    disclaimer_block = [RISK_DISCLAIMER.strip()]
    logger.info("\n".join(disclaimer_block))
    

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
    compliance_block = [
        "📜 FINANCIAL COMPLIANCE NOTICE",
        "Risk disclosure sections A/B/C were logged at startup for audit purposes.",
    ]
    logger.info("\n".join(compliance_block))
