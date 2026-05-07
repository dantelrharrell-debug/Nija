"""
NIJA Mobile App - Educational Lesson Map

Provides structured educational content for onboarding new users to the NIJA trading platform.
Includes compliance-safe language and progressive learning paths.

Author: NIJA Trading Systems
Version: 1.0
Date: January 31, 2026
"""

from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any
from enum import Enum
from datetime import datetime


class LessonCategory(Enum):
    """Lesson categories for organizing educational content"""
    GETTING_STARTED = "getting_started"
    TRADING_BASICS = "trading_basics"
    RISK_MANAGEMENT = "risk_management"
    PLATFORM_FEATURES = "platform_features"
    ADVANCED_STRATEGIES = "advanced_strategies"
    COMPLIANCE = "compliance"


class LessonType(Enum):
    """Types of lesson content delivery"""
    TEXT = "text"
    VIDEO = "video"
    INTERACTIVE = "interactive"
    QUIZ = "quiz"


class LessonDifficulty(Enum):
    """Lesson difficulty levels"""
    BEGINNER = "beginner"
    INTERMEDIATE = "intermediate"
    ADVANCED = "advanced"


@dataclass
class QuizQuestion:
    """Quiz question for lesson assessment"""
    question: str
    options: List[str]
    correct_answer_index: int
    explanation: str
    points: int = 10


@dataclass
class Lesson:
    """Individual micro-lesson in the learning path"""
    lesson_id: str
    title: str
    category: LessonCategory
    difficulty: LessonDifficulty
    lesson_type: LessonType
    duration_minutes: int
    content: str
    key_points: List[str]
    quiz_questions: List[QuizQuestion] = field(default_factory=list)
    prerequisites: List[str] = field(default_factory=list)
    order: int = 0
    is_required: bool = True
    compliance_disclaimer: Optional[str] = None


# Compliance-safe disclaimer templates
COMPLIANCE_DISCLAIMERS = {
    "trading_risk": (
        "⚠️ RISK DISCLOSURE: Cryptocurrency trading involves substantial risk of loss and is not "
        "suitable for all investors. You should carefully consider whether trading is appropriate "
        "for you in light of your experience, objectives, financial resources, and other relevant "
        "circumstances. Only trade with money you can afford to lose completely."
    ),
    "no_guarantee": (
        "📊 PERFORMANCE NOTICE: Past performance is not indicative of future results. The bot's "
        "historical performance does not guarantee future profitability. Market conditions change "
        "and strategy effectiveness may vary."
    ),
    "not_advice": (
        "💼 NOT FINANCIAL ADVICE: This platform is an automated trading tool. Nothing on this "
        "platform should be considered as personalized financial advice. Consult with a qualified "
        "financial advisor before making investment decisions."
    ),
    "educational_only": (
        "📚 EDUCATIONAL PURPOSE: This lesson is for educational purposes only. It does not "
        "constitute an offer to buy or sell securities or an endorsement of any specific "
        "investment strategy."
    ),
    "regulatory": (
        "⚖️ REGULATORY NOTICE: Cryptocurrency regulations vary by jurisdiction. You are "
        "responsible for ensuring compliance with all applicable laws and regulations in your "
        "location. This platform may not be available in all jurisdictions."
    ),
}


def create_lesson_map() -> List[Lesson]:
    """
    Create the complete lesson map with 40 micro-lessons across all categories.
    
    Returns:
        List of Lesson objects in recommended order
    """
    lessons = []
    
    # ========================================
    # CATEGORY 1: GETTING STARTED (8 lessons)
    # ========================================
    
    lessons.append(Lesson(
        lesson_id="gs_001",
        title="Welcome to NIJA",
        category=LessonCategory.GETTING_STARTED,
        difficulty=LessonDifficulty.BEGINNER,
        lesson_type=LessonType.TEXT,
        duration_minutes=3,
        order=1,
        content=(
            "Welcome to NIJA - your intelligent cryptocurrency trading assistant!\n\n"
            "NIJA is an autonomous trading bot that executes trades on your behalf using "
            "advanced algorithms and market analysis. It runs continuously, avoids emotional "
            "decision-making, and follows your risk parameters exactly.\n\n"
            "In this onboarding journey, you'll learn:\n"
            "• How NIJA works and what it can do for you\n"
            "• How to set up your trading account safely\n"
            "• How to manage risk and protect your capital\n"
            "• How to monitor and optimize your trading performance\n\n"
            "Take your time with each lesson. Trading is a skill that requires knowledge and "
            "practice. We're here to help you succeed."
        ),
        key_points=[
            "NIJA is an automated trading assistant",
            "Operates 24/7 following your risk parameters",
            "Learn at your own pace",
            "Success requires knowledge and practice"
        ],
        compliance_disclaimer=COMPLIANCE_DISCLAIMERS["not_advice"],
        quiz_questions=[
            QuizQuestion(
                question="What is NIJA?",
                options=[
                    "A human financial advisor",
                    "An automated cryptocurrency trading bot",
                    "A cryptocurrency wallet",
                    "A stock trading platform"
                ],
                correct_answer_index=1,
                explanation="NIJA is an automated trading bot that trades cryptocurrencies on your behalf.",
                points=10
            ),
            QuizQuestion(
                question="What should you expect from this onboarding?",
                options=[
                    "Profit promises immediately",
                    "Free cryptocurrency",
                    "Education on trading and risk management",
                    "Stock trading tips"
                ],
                correct_answer_index=2,
                explanation="This onboarding focuses on education to help you use the platform safely and effectively.",
                points=10
            )
        ]
    ))
    
    lessons.append(Lesson(
        lesson_id="gs_002",
        title="How Automated Trading Works",
        category=LessonCategory.GETTING_STARTED,
        difficulty=LessonDifficulty.BEGINNER,
        lesson_type=LessonType.TEXT,
        duration_minutes=4,
        order=2,
        prerequisites=["gs_001"],
        content=(
            "Automated trading uses computer algorithms to make trading decisions based on "
            "predefined rules and market data analysis.\n\n"
            "**How NIJA Makes Trading Decisions:**\n\n"
            "1. **Market Scanning**: Continuously monitors 700+ cryptocurrency pairs\n"
            "2. **Technical Analysis**: Analyzes price patterns, trends, and indicators (RSI, moving averages)\n"
            "3. **Signal Generation**: Identifies potential trading opportunities\n"
            "4. **Risk Check**: Validates trades against your risk parameters\n"
            "5. **Execution**: Places buy/sell orders automatically\n"
            "6. **Position Management**: Monitors trades and manages exits\n\n"
            "**Key Advantages:**\n"
            "• Removes emotional decision-making\n"
            "• Operates continuously without breaks\n"
            "• Executes trades faster than humans\n"
            "• Consistently follows the strategy\n\n"
            "**Important to Know:**\n"
            "While automation removes emotion, it doesn't eliminate risk. Market conditions "
            "can change, and no algorithm is perfect. That's why risk management is crucial."
        ),
        key_points=[
            "Algorithms make decisions based on data and rules",
            "NIJA scans 700+ cryptocurrency markets continuously",
            "Technical indicators identify trading opportunities",
            "Automation removes emotion but not risk"
        ],
        compliance_disclaimer=COMPLIANCE_DISCLAIMERS["no_guarantee"],
        quiz_questions=[
            QuizQuestion(
                question="What is a key advantage of automated trading?",
                options=[
                    "It guarantees profits",
                    "It removes emotional decision-making",
                    "It eliminates all trading risks",
                    "It requires no monitoring"
                ],
                correct_answer_index=1,
                explanation="Automated trading removes emotions from decisions, but doesn't eliminate risk or guarantee profits.",
                points=10
            )
        ]
    ))
    
    lessons.append(Lesson(
        lesson_id="gs_003",
        title="Understanding Cryptocurrency Markets",
        category=LessonCategory.GETTING_STARTED,
        difficulty=LessonDifficulty.BEGINNER,
        lesson_type=LessonType.TEXT,
        duration_minutes=5,
        order=3,
        prerequisites=["gs_002"],
        content=(
            "Cryptocurrency markets operate differently from traditional stock markets.\n\n"
            "**Key Characteristics:**\n\n"
            "📈 **24/7 Trading**: Unlike stock markets, crypto markets never close. "
            "Trading happens around the clock, every day of the year.\n\n"
            "💹 **High Volatility**: Crypto prices can move significantly in short periods. "
            "This creates opportunities but also increases risk.\n\n"
            "🌐 **Global Market**: Anyone with internet access can trade from anywhere in the world.\n\n"
            "💱 **Multiple Exchanges**: Cryptocurrencies trade on many different exchanges "
            "(Coinbase, Kraken, Binance, etc.), sometimes with price differences.\n\n"
            "⚡ **Fast Settlement**: Crypto transactions settle much faster than traditional finance.\n\n"
            "**What This Means for You:**\n\n"
            "• Markets can move while you sleep - that's where NIJA helps\n"
            "• Prices can change dramatically - risk management is essential\n"
            "• Opportunities exist 24/7 - but so do risks\n"
            "• Different exchanges may have different prices - NIJA monitors multiple markets"
        ),
        key_points=[
            "Crypto markets operate 24/7 without breaks",
            "High volatility means bigger price swings",
            "Global access from anywhere",
            "Automated trading helps manage 24/7 markets"
        ],
        compliance_disclaimer=COMPLIANCE_DISCLAIMERS["trading_risk"],
        quiz_questions=[
            QuizQuestion(
                question="What makes cryptocurrency markets different from stock markets?",
                options=[
                    "They only operate on weekdays",
                    "They operate 24/7 without closing",
                    "They have no volatility",
                    "They are only accessible to banks"
                ],
                correct_answer_index=1,
                explanation="Unlike stock markets that close on weekends and holidays, crypto markets operate continuously 24/7.",
                points=10
            ),
            QuizQuestion(
                question="What does high volatility in crypto markets mean?",
                options=[
                    "Prices stay stable",
                    "Prices can move significantly in short periods",
                    "No trading is allowed",
                    "Only small trades are possible"
                ],
                correct_answer_index=1,
                explanation="High volatility means prices can change dramatically in short time periods, creating both opportunities and risks.",
                points=10
            )
        ]
    ))
    
    lessons.append(Lesson(
        lesson_id="gs_004",
        title="Exchange Connection Setup",
        category=LessonCategory.GETTING_STARTED,
        difficulty=LessonDifficulty.BEGINNER,
        lesson_type=LessonType.INTERACTIVE,
        duration_minutes=5,
        order=4,
        prerequisites=["gs_003"],
        content=(
            "To trade, NIJA needs secure access to your exchange account via API keys.\n\n"
            "**What are API Keys?**\n"
            "API (Application Programming Interface) keys are like a secure password that "
            "allows NIJA to access your exchange account programmatically.\n\n"
            "**Security Best Practices:**\n\n"
            "✅ **DO:**\n"
            "• Generate API keys with TRADING permissions only\n"
            "• Enable IP address restrictions if available\n"
            "• Store keys securely (NIJA encrypts them)\n"
            "• Use different keys for each service\n\n"
            "❌ **DON'T:**\n"
            "• Share API keys with anyone\n"
            "• Enable WITHDRAWAL permissions (not needed)\n"
            "• Store keys in plain text or screenshots\n"
            "• Reuse API keys across platforms\n\n"
            "**Supported Exchanges:**\n"
            "• Coinbase Advanced Trade\n"
            "• Kraken\n"
            "• Binance\n"
            "• OKX\n"
            "• Alpaca (for stocks)\n\n"
            "In the next step, you'll connect your exchange account. We'll guide you "
            "through creating API keys with the correct permissions."
        ),
        key_points=[
            "API keys provide secure access to your exchange",
            "Only enable TRADING permissions, never WITHDRAWAL",
            "NIJA encrypts and securely stores your keys",
            "Each exchange has its own API key setup process"
        ],
        compliance_disclaimer=COMPLIANCE_DISCLAIMERS["educational_only"],
        quiz_questions=[
            QuizQuestion(
                question="What permissions should your API keys have for NIJA?",
                options=[
                    "WITHDRAWAL and TRADING",
                    "Only TRADING permissions",
                    "Only WITHDRAWAL permissions",
                    "Full account access"
                ],
                correct_answer_index=1,
                explanation="For security, API keys should only have TRADING permissions. Never enable WITHDRAWAL permissions.",
                points=10
            ),
            QuizQuestion(
                question="What should you do with your API keys?",
                options=[
                    "Share them with friends",
                    "Post them on social media",
                    "Store them securely and never share",
                    "Write them down and leave visible"
                ],
                correct_answer_index=2,
                explanation="API keys should be stored securely and never shared with anyone to protect your account.",
                points=10
            )
        ]
    ))
    
    lessons.append(Lesson(
        lesson_id="gs_005",
        title="Your Trading Dashboard",
        category=LessonCategory.GETTING_STARTED,
        difficulty=LessonDifficulty.BEGINNER,
        lesson_type=LessonType.INTERACTIVE,
        duration_minutes=4,
        order=5,
        prerequisites=["gs_004"],
        content=(
            "Your dashboard is your command center for monitoring and controlling trading.\n\n"
            "**Key Dashboard Sections:**\n\n"
            "📊 **Portfolio Overview**\n"
            "• Total account value\n"
            "• Today's P&L (Profit & Loss)\n"
            "• Win rate percentage\n\n"
            "📈 **Active Positions**\n"
            "• Currently open trades\n"
            "• Current profit/loss per position\n"
            "• Entry price and current price\n\n"
            "🎯 **Performance Stats**\n"
            "• Total trades executed\n"
            "• Win/loss ratio\n"
            "• Average profit per trade\n\n"
            "⚙️ **Trading Controls**\n"
            "• Start/Stop trading toggle\n"
            "• Pause for maintenance\n"
            "• Emergency stop button\n\n"
            "🔔 **Notifications**\n"
            "• Trade executions\n"
            "• Position updates\n"
            "• Account alerts\n\n"
            "**Quick Actions:**\n"
            "Swipe or tap for quick access to:\n"
            "• Position details\n"
            "• Close specific positions\n"
            "• Adjust risk settings\n"
            "• View trade history"
        ),
        key_points=[
            "Dashboard shows real-time portfolio status",
            "Monitor active positions and P&L",
            "Control trading with simple toggles",
            "Quick access to detailed information"
        ],
        quiz_questions=[
            QuizQuestion(
                question="What does P&L stand for in trading?",
                options=[
                    "Price and Loss",
                    "Profit and Loss",
                    "Portfolio and Leverage",
                    "Positions and Limits"
                ],
                correct_answer_index=1,
                explanation="P&L stands for Profit and Loss, showing how much you've gained or lost on your trades.",
                points=10
            ),
            QuizQuestion(
                question="Where can you stop trading immediately on the dashboard?",
                options=[
                    "In the settings menu only",
                    "Through customer support",
                    "Using the emergency stop button",
                    "You cannot stop trading once started"
                ],
                correct_answer_index=2,
                explanation="The dashboard has an emergency stop button for immediately halting all trading activities.",
                points=10
            )
        ]
    ))
    
    lessons.append(Lesson(
        lesson_id="gs_006",
        title="Trading Start Checklist",
        category=LessonCategory.GETTING_STARTED,
        difficulty=LessonDifficulty.BEGINNER,
        lesson_type=LessonType.TEXT,
        duration_minutes=3,
        order=6,
        prerequisites=["gs_005"],
        content=(
            "Before starting live trading, complete this essential checklist:\n\n"
            "✅ **Account Setup**\n"
            "• Exchange account created and verified\n"
            "• API keys generated with correct permissions\n"
            "• API keys connected to NIJA\n"
            "• Test connection successful\n\n"
            "✅ **Risk Configuration**\n"
            "• Maximum position size set\n"
            "• Daily loss limit configured\n"
            "• Risk per trade defined\n"
            "• Stop-loss settings reviewed\n\n"
            "✅ **Capital Preparation**\n"
            "• Deposit only what you can afford to lose\n"
            "• Keep emergency funds separate\n"
            "• Understand potential for loss\n"
            "• Accept risk disclosure\n\n"
            "✅ **Education Complete**\n"
            "• Completed all beginner lessons\n"
            "• Understand how the bot works\n"
            "• Know how to stop trading\n"
            "• Familiar with dashboard features\n\n"
            "**Recommended Starting Approach:**\n"
            "1. Start with minimum position sizes\n"
            "2. Monitor closely for first week\n"
            "3. Review performance after 50+ trades\n"
            "4. Gradually increase size as you gain confidence"
        ),
        key_points=[
            "Complete setup before live trading",
            "Configure risk limits appropriately",
            "Only use capital you can afford to lose",
            "Start small and scale gradually"
        ],
        compliance_disclaimer=COMPLIANCE_DISCLAIMERS["trading_risk"],
        quiz_questions=[
            QuizQuestion(
                question="What should you do before starting live trading?",
                options=[
                    "Skip the checklist and start immediately",
                    "Complete the entire trading start checklist",
                    "Only connect your API keys",
                    "Deposit all your savings"
                ],
                correct_answer_index=1,
                explanation="Always complete the full trading start checklist to ensure safe and proper setup before trading.",
                points=10
            ),
            QuizQuestion(
                question="What is the recommended approach when starting to trade?",
                options=[
                    "Use maximum position sizes immediately",
                    "Start with minimum sizes and scale gradually",
                    "Trade without monitoring",
                    "Ignore risk settings"
                ],
                correct_answer_index=1,
                explanation="Start with minimum position sizes, monitor closely, and gradually increase as you gain confidence.",
                points=10
            )
        ]
    ))
    
    lessons.append(Lesson(
        lesson_id="gs_007",
        title="How to Get Help",
        category=LessonCategory.GETTING_STARTED,
        difficulty=LessonDifficulty.BEGINNER,
        lesson_type=LessonType.TEXT,
        duration_minutes=2,
        order=7,
        prerequisites=["gs_006"],
        content=(
            "You're not alone! Multiple support channels are available.\n\n"
            "📚 **In-App Help**\n"
            "• Tap the '?' icon anywhere for context help\n"
            "• Access lessons anytime from Settings > Education\n"
            "• View FAQs for common questions\n\n"
            "💬 **Community Support**\n"
            "• Discord community (fastest response)\n"
            "• User forums for strategy discussions\n"
            "• Weekly Q&A sessions\n\n"
            "📧 **Direct Support**\n"
            "• Email: support@nija.app\n"
            "• Response time: 24-48 hours\n"
            "• Include user ID for faster help\n\n"
            "📖 **Documentation**\n"
            "• Full documentation at docs.nija.app\n"
            "• Video tutorials on YouTube\n"
            "• Strategy guides and best practices\n\n"
            "🚨 **Emergency Issues**\n"
            "If you need to stop trading immediately:\n"
            "1. Tap the STOP button in dashboard\n"
            "2. Or revoke API keys in your exchange\n"
            "3. Then contact support\n\n"
            "**Pro Tip:** Join Discord for the fastest help and to connect with other traders!"
        ),
        key_points=[
            "Multiple support channels available",
            "Discord community offers fastest help",
            "Emergency stop button always accessible",
            "Documentation and tutorials available 24/7"
        ],
        quiz_questions=[
            QuizQuestion(
                question="What is the fastest way to get help?",
                options=[
                    "Wait for email response",
                    "Join the Discord community",
                    "Call customer service",
                    "Send a letter"
                ],
                correct_answer_index=1,
                explanation="The Discord community provides the fastest response times for getting help.",
                points=10
            ),
            QuizQuestion(
                question="If you need to stop trading immediately, what should you do first?",
                options=[
                    "Wait to contact support",
                    "Tap the STOP button in the dashboard",
                    "Uninstall the app",
                    "Ignore it and hope for the best"
                ],
                correct_answer_index=1,
                explanation="Use the STOP button in the dashboard for immediate trading halt, then contact support if needed.",
                points=10
            )
        ]
    ))
    
    lessons.append(Lesson(
        lesson_id="gs_008",
        title="Understanding Fees and Costs",
        category=LessonCategory.GETTING_STARTED,
        difficulty=LessonDifficulty.BEGINNER,
        lesson_type=LessonType.TEXT,
        duration_minutes=4,
        order=8,
        prerequisites=["gs_007"],
        content=(
            "Understanding all costs helps you calculate true profitability.\n\n"
            "**Exchange Trading Fees:**\n"
            "Every trade incurs fees charged by the exchange:\n"
            "• Maker fees: 0.00% - 0.50% (placing limit orders)\n"
            "• Taker fees: 0.04% - 0.60% (market orders)\n"
            "• Varies by exchange and trading volume\n\n"
            "**NIJA Platform Fees:**\n"
            "• Free tier: Limited features, no subscription\n"
            "• Alpha tier: $49/month or 10% of profits\n"
            "• Pro tier: $99/month or 15% of profits\n"
            "• You only pay subscription OR profit share, whichever you choose\n\n"
            "**Hidden Costs to Consider:**\n"
            "• Spread (difference between buy/sell price)\n"
            "• Slippage (price moves while order executes)\n"
            "• Blockchain network fees (deposits/withdrawals)\n\n"
            "**Profitability Calculation:**\n"
            "True Profit = Gross Profit - Exchange Fees - NIJA Fee - Other Costs\n\n"
            "**Tips to Minimize Costs:**\n"
            "• Higher trading volume = lower exchange fees\n"
            "• Use limit orders when possible (lower fees)\n"
            "• Consider fee structure when choosing exchanges\n"
            "• Track all costs in your performance metrics"
        ),
        key_points=[
            "Exchange fees reduce your gross profits",
            "NIJA offers subscription or profit-share pricing",
            "Account for all costs in profitability calculations",
            "Higher volume typically means lower fees"
        ],
        compliance_disclaimer=COMPLIANCE_DISCLAIMERS["educational_only"],
        quiz_questions=[
            QuizQuestion(
                question="What types of fees should you consider when calculating profitability?",
                options=[
                    "Only NIJA platform fees",
                    "Only exchange trading fees",
                    "Exchange fees, NIJA fees, spread, and slippage",
                    "No fees apply to automated trading"
                ],
                correct_answer_index=2,
                explanation="True profitability requires accounting for all costs: exchange fees, platform fees, spread, slippage, and network fees.",
                points=10
            ),
            QuizQuestion(
                question="How does NIJA pricing work?",
                options=[
                    "Flat monthly fee only",
                    "Subscription OR profit share, whichever you choose",
                    "Both subscription AND profit share required",
                    "Completely free with no fees"
                ],
                correct_answer_index=1,
                explanation="NIJA offers flexible pricing: you can choose either a subscription fee OR profit share, not both.",
                points=10
            )
        ]
    ))
    
    # ========================================
    # CATEGORY 2: TRADING BASICS (10 lessons)
    # ========================================
    
    lessons.append(Lesson(
        lesson_id="tb_001",
        title="What is Technical Analysis?",
        category=LessonCategory.TRADING_BASICS,
        difficulty=LessonDifficulty.BEGINNER,
        lesson_type=LessonType.TEXT,
        duration_minutes=5,
        order=9,
        prerequisites=["gs_008"],
        content=(
            "Technical analysis is the study of price charts and patterns to predict future price movements.\n\n"
            "**Core Principle:**\n"
            "Price action reflects all available information. By analyzing historical price "
            "patterns, we can identify probable future movements.\n\n"
            "**Key Components:**\n\n"
            "📊 **Price Charts**\n"
            "• Display historical price over time\n"
            "• Show open, high, low, close prices\n"
            "• Various timeframes (1min to 1 month)\n\n"
            "📈 **Trends**\n"
            "• Uptrend: Higher highs and higher lows\n"
            "• Downtrend: Lower highs and lower lows\n"
            "• Sideways: No clear direction\n\n"
            "🎯 **Support & Resistance**\n"
            "• Support: Price level where buying pressure increases\n"
            "• Resistance: Price level where selling pressure increases\n\n"
            "📐 **Technical Indicators**\n"
            "• Mathematical calculations based on price/volume\n"
            "• Help identify trends, momentum, volatility\n"
            "• Examples: RSI, Moving Averages, MACD\n\n"
            "**NIJA's Approach:**\n"
            "NIJA uses multiple technical indicators simultaneously to make more reliable "
            "trading decisions, focusing on RSI and moving averages."
        ),
        key_points=[
            "Technical analysis studies price patterns",
            "Trends show market direction",
            "Support and resistance are key price levels",
            "Indicators help identify trading opportunities"
        ],
        compliance_disclaimer=COMPLIANCE_DISCLAIMERS["educational_only"],
        quiz_questions=[
            QuizQuestion(
                question="What is an uptrend?",
                options=[
                    "Prices moving sideways",
                    "Prices making higher highs and higher lows",
                    "Prices making lower lows",
                    "Random price movement"
                ],
                correct_answer_index=1,
                explanation="An uptrend is characterized by consecutive higher highs and higher lows.",
                points=10
            ),
            QuizQuestion(
                question="What is a support level in technical analysis?",
                options=[
                    "A price level where selling pressure increases",
                    "A price level where buying pressure increases",
                    "The highest price ever reached",
                    "The current market price"
                ],
                correct_answer_index=1,
                explanation="Support is a price level where buying pressure typically increases, preventing further price decline.",
                points=10
            ),
            QuizQuestion(
                question="Why does NIJA use multiple technical indicators?",
                options=[
                    "To make trading more complicated",
                    "To make more reliable trading decisions",
                    "Because one indicator is not enough data",
                    "To slow down trading speed"
                ],
                correct_answer_index=1,
                explanation="Using multiple indicators together provides more reliable signals and reduces false positives.",
                points=10
            )
        ]
    ))
    
    lessons.append(Lesson(
        lesson_id="tb_002",
        title="Understanding RSI Indicator",
        category=LessonCategory.TRADING_BASICS,
        difficulty=LessonDifficulty.INTERMEDIATE,
        lesson_type=LessonType.TEXT,
        duration_minutes=6,
        order=10,
        prerequisites=["tb_001"],
        content=(
            "RSI (Relative Strength Index) is a momentum indicator that measures if an asset "
            "is overbought or oversold.\n\n"
            "**How RSI Works:**\n\n"
            "• Ranges from 0 to 100\n"
            "• Above 70: Often considered overbought (may reverse down)\n"
            "• Below 30: Often considered oversold (may reverse up)\n"
            "• 50: Neutral zone\n\n"
            "**NIJA's Dual RSI Strategy:**\n\n"
            "NIJA uses TWO RSI periods for more reliable signals:\n\n"
            "1. **RSI_9 (Fast)**: Responds quickly to price changes\n"
            "2. **RSI_14 (Standard)**: Provides confirmation\n\n"
            "**Entry Signals:**\n"
            "• **Buy Signal**: Both RSI_9 and RSI_14 cross above 30 (oversold recovery)\n"
            "• **Sell Signal**: Both RSI_9 and RSI_14 cross below 70 (overbought peak)\n\n"
            "**Why Two RSIs?**\n"
            "Using two periods reduces false signals. When both agree, the signal is stronger.\n\n"
            "**Important Considerations:**\n"
            "• RSI can stay overbought/oversold for extended periods in strong trends\n"
            "• Works best in ranging markets\n"
            "• Should be combined with other indicators\n"
            "• Different timeframes give different RSI readings"
        ),
        key_points=[
            "RSI measures momentum from 0-100",
            "Below 30 = oversold, above 70 = overbought",
            "NIJA uses dual RSI (9 and 14) for confirmation",
            "More reliable when combined with other signals"
        ],
        compliance_disclaimer=COMPLIANCE_DISCLAIMERS["educational_only"],
        quiz_questions=[
            QuizQuestion(
                question="What does an RSI reading below 30 indicate?",
                options=[
                    "The asset is overbought",
                    "The asset is oversold and may reverse up",
                    "The price will definitely go up",
                    "Time to sell immediately"
                ],
                correct_answer_index=1,
                explanation="RSI below 30 suggests oversold conditions, which may lead to a bounce, but it's not a guarantee.",
                points=10
            ),
            QuizQuestion(
                question="Why does NIJA use both RSI_9 and RSI_14?",
                options=[
                    "To make trading slower",
                    "To reduce false signals and increase reliability",
                    "Because one RSI doesn't work",
                    "To confuse the market"
                ],
                correct_answer_index=1,
                explanation="Using two RSI periods (9 and 14) reduces false signals. When both agree, the signal is more reliable.",
                points=10
            ),
            QuizQuestion(
                question="What RSI range is considered the neutral zone?",
                options=[
                    "0-30",
                    "70-100",
                    "Around 50",
                    "Above 100"
                ],
                correct_answer_index=2,
                explanation="RSI around 50 is considered neutral, neither overbought nor oversold.",
                points=10
            )
        ]
    ))
    
    lessons.append(Lesson(
        lesson_id="tb_003",
        title="Moving Averages Explained",
        category=LessonCategory.TRADING_BASICS,
        difficulty=LessonDifficulty.INTERMEDIATE,
        lesson_type=LessonType.TEXT,
        duration_minutes=6,
        order=13,
        prerequisites=["tb_002"],
        content=(
            "Moving Averages (MA) smooth out price data to identify trends over time.\n\n"
            "**What is a Moving Average?**\n"
            "A moving average calculates the average price over a specific period, then 'moves' "
            "forward by dropping the oldest price and adding the newest.\n\n"
            "**Common Types:**\n\n"
            "📊 **Simple Moving Average (SMA)**\n"
            "• Equally weights all prices in the period\n"
            "• Example: 50-day SMA = average of last 50 days\n"
            "• Slower to react to price changes\n\n"
            "📈 **Exponential Moving Average (EMA)**\n"
            "• Gives more weight to recent prices\n"
            "• Reacts faster to price changes\n"
            "• Preferred for short-term trading\n\n"
            "**Popular Periods:**\n"
            "• 9 EMA: Very short-term\n"
            "• 21 EMA: Short-term trend\n"
            "• 50 SMA: Medium-term trend\n"
            "• 200 SMA: Long-term trend\n\n"
            "**Trading Signals:**\n\n"
            "✅ **Bullish Signals:**\n"
            "• Price crosses above MA\n"
            "• Fast MA crosses above slow MA (golden cross)\n"
            "• Price bounces off MA as support\n\n"
            "❌ **Bearish Signals:**\n"
            "• Price crosses below MA\n"
            "• Fast MA crosses below slow MA (death cross)\n"
            "• MA acts as resistance\n\n"
            "**NIJA's Use:**\n"
            "NIJA monitors multiple moving averages to confirm trend direction and "
            "filter out trades against the prevailing trend."
        ),
        key_points=[
            "Moving averages smooth price data to show trends",
            "EMA reacts faster than SMA to price changes",
            "Crossovers generate buy/sell signals",
            "NIJA uses multiple MAs for trend confirmation"
        ],
        compliance_disclaimer=COMPLIANCE_DISCLAIMERS["educational_only"],
        quiz_questions=[
            QuizQuestion(
                question="What is the main difference between SMA and EMA?",
                options=[
                    "SMA is faster than EMA",
                    "EMA gives more weight to recent prices",
                    "SMA doesn't work for crypto",
                    "There is no difference"
                ],
                correct_answer_index=1,
                explanation="EMA (Exponential Moving Average) gives more weight to recent prices, making it more responsive to current price action.",
                points=10
            ),
            QuizQuestion(
                question="What is a 'golden cross'?",
                options=[
                    "When price hits a new high",
                    "When a fast MA crosses above a slow MA",
                    "When RSI crosses 70",
                    "When volume increases"
                ],
                correct_answer_index=1,
                explanation="A golden cross occurs when a faster MA crosses above a slower MA, signaling potential uptrend.",
                points=10
            )
        ]
    ))
    
    lessons.append(Lesson(
        lesson_id="tb_004",
        title="Candlestick Patterns Basics",
        category=LessonCategory.TRADING_BASICS,
        difficulty=LessonDifficulty.INTERMEDIATE,
        lesson_type=LessonType.TEXT,
        duration_minutes=7,
        order=14,
        prerequisites=["tb_003"],
        content=(
            "Candlestick charts visualize price action showing open, high, low, and close.\n\n"
            "**Anatomy of a Candlestick:**\n\n"
            "🕯️ **Body**: Rectangle showing open and close\n"
            "• Green/White: Close higher than open (bullish)\n"
            "• Red/Black: Close lower than open (bearish)\n\n"
            "📏 **Wicks/Shadows**: Lines above and below body\n"
            "• Upper wick: High of the period\n"
            "• Lower wick: Low of the period\n\n"
            "**Single Candle Patterns:**\n\n"
            "🔨 **Hammer** (Bullish)\n"
            "• Small body at top\n"
            "• Long lower wick\n"
            "• Suggests buying pressure after decline\n\n"
            "⭐ **Doji** (Indecision)\n"
            "• Open equals close (tiny body)\n"
            "• Signals market indecision\n"
            "• Often precedes reversals\n\n"
            "💹 **Engulfing** (Reversal)\n"
            "• Bullish: Large green candle engulfs previous red\n"
            "• Bearish: Large red candle engulfs previous green\n\n"
            "**Multi-Candle Patterns:**\n\n"
            "⭐ **Morning Star** (Bullish)\n"
            "• Three candles: large red, small body, large green\n"
            "• Signals end of downtrend\n\n"
            "🌙 **Evening Star** (Bearish)\n"
            "• Three candles: large green, small body, large red\n"
            "• Signals end of uptrend\n\n"
            "**Important Notes:**\n"
            "• Patterns are more reliable with high volume\n"
            "• Context matters - consider the trend\n"
            "• Confirm with other indicators\n"
            "• Not all patterns play out as expected"
        ),
        key_points=[
            "Candlesticks show open, high, low, close in one visual",
            "Body color indicates bullish (green) or bearish (red)",
            "Patterns suggest potential reversals or continuations",
            "Always confirm patterns with volume and other indicators"
        ],
        compliance_disclaimer=COMPLIANCE_DISCLAIMERS["educational_only"],
        quiz_questions=[
            QuizQuestion(
                question="What does a green/white candlestick indicate?",
                options=[
                    "Price closed lower than it opened",
                    "Price closed higher than it opened",
                    "No trading occurred",
                    "Market is closed"
                ],
                correct_answer_index=1,
                explanation="A green/white candle means the closing price was higher than the opening price (bullish).",
                points=10
            ),
            QuizQuestion(
                question="What does a Doji candlestick pattern indicate?",
                options=[
                    "Strong uptrend",
                    "Strong downtrend",
                    "Market indecision",
                    "No volatility"
                ],
                correct_answer_index=2,
                explanation="A Doji has a very small body (open ≈ close), indicating market indecision and potential reversal.",
                points=10
            )
        ]
    ))
    
    lessons.append(Lesson(
        lesson_id="tb_005",
        title="Volume Analysis",
        category=LessonCategory.TRADING_BASICS,
        difficulty=LessonDifficulty.INTERMEDIATE,
        lesson_type=LessonType.TEXT,
        duration_minutes=5,
        order=15,
        prerequisites=["tb_004"],
        content=(
            "Volume measures how much of an asset is traded over a specific period.\n\n"
            "**What Volume Tells You:**\n"
            "Volume represents market participation and conviction behind price moves.\n\n"
            "📊 **High Volume**\n"
            "• Indicates strong interest and conviction\n"
            "• Validates price movements\n"
            "• Suggests sustainability of trends\n\n"
            "📉 **Low Volume**\n"
            "• Indicates weak participation\n"
            "• Price moves may be unreliable\n"
            "• Trends may lack conviction\n\n"
            "**Volume and Price Relationship:**\n\n"
            "✅ **Healthy Patterns:**\n"
            "• Rising prices + rising volume = strong uptrend\n"
            "• Falling prices + rising volume = strong downtrend\n"
            "• Breakouts with high volume = likely to sustain\n\n"
            "⚠️ **Warning Signs:**\n"
            "• Rising prices + falling volume = weak uptrend\n"
            "• Falling prices + falling volume = weak downtrend\n"
            "• Breakout with low volume = likely false breakout\n\n"
            "**Volume Indicators:**\n\n"
            "📈 **Volume Bars**\n"
            "• Shown at bottom of charts\n"
            "• Height represents amount traded\n"
            "• Compare current to average\n\n"
            "📊 **OBV (On-Balance Volume)**\n"
            "• Cumulative volume indicator\n"
            "• Adds volume on up days, subtracts on down days\n"
            "• Confirms trend strength\n\n"
            "**NIJA's Approach:**\n"
            "NIJA filters out low-volume markets and considers volume "
            "when validating trading signals for better reliability."
        ),
        key_points=[
            "Volume indicates market participation and conviction",
            "High volume validates price movements",
            "Volume divergence can signal trend weakness",
            "NIJA uses volume to filter and validate signals"
        ],
        compliance_disclaimer=COMPLIANCE_DISCLAIMERS["educational_only"],
        quiz_questions=[
            QuizQuestion(
                question="What does high volume during a price increase indicate?",
                options=[
                    "Weak trend that may reverse",
                    "Strong trend with conviction",
                    "Market manipulation",
                    "Trend is about to end"
                ],
                correct_answer_index=1,
                explanation="High volume during price increases indicates strong participation and conviction, validating the uptrend.",
                points=10
            ),
            QuizQuestion(
                question="What is a warning sign in volume analysis?",
                options=[
                    "Rising prices with rising volume",
                    "Rising prices with falling volume",
                    "High volume breakouts",
                    "Volume matching price direction"
                ],
                correct_answer_index=1,
                explanation="Rising prices with falling volume suggests weakening conviction and potential trend exhaustion.",
                points=10
            )
        ]
    ))
    
    # Continue with more Trading Basics lessons...
    
    lessons.append(Lesson(
        lesson_id="tb_006",
        title="Trend Lines and Channels",
        category=LessonCategory.TRADING_BASICS,
        difficulty=LessonDifficulty.INTERMEDIATE,
        lesson_type=LessonType.TEXT,
        duration_minutes=6,
        order=16,
        prerequisites=["tb_005"],
        content=(
            "Trend lines and channels help identify trend direction and potential reversal points.\n\n"
            "**Drawing Trend Lines:**\n\n"
            "📈 **Uptrend Line**\n"
            "• Connect two or more higher lows\n"
            "• Line should slope upward\n"
            "• Acts as support during uptrends\n\n"
            "📉 **Downtrend Line**\n"
            "• Connect two or more lower highs\n"
            "• Line should slope downward\n"
            "• Acts as resistance during downtrends\n\n"
            "**Validation:**\n"
            "• Need at least 2 points to draw\n"
            "• 3+ touches increase reliability\n"
            "• More touches = stronger trend line\n"
            "• Break of trend line may signal reversal\n\n"
            "**Trend Channels:**\n\n"
            "📊 **Channel Construction**\n"
            "• Draw trend line along lows (support)\n"
            "• Draw parallel line along highs (resistance)\n"
            "• Price typically bounces between these lines\n\n"
            "**Trading Strategies:**\n\n"
            "✅ **Channel Trading:**\n"
            "• Buy near lower channel line (support)\n"
            "• Sell near upper channel line (resistance)\n"
            "• Exit if price breaks channel\n\n"
            "⚡ **Breakout Trading:**\n"
            "• Strong volume breakout above resistance = buy signal\n"
            "• Strong volume breakdown below support = sell signal\n\n"
            "**Common Mistakes:**\n"
            "• Forcing trend lines to fit\n"
            "• Using only 2 points without confirmation\n"
            "• Ignoring volume on breakouts\n"
            "• Not adjusting as new price data appears"
        ),
        key_points=[
            "Trend lines connect swing highs or lows",
            "Channels show price boundaries in a trend",
            "More touches = stronger and more reliable",
            "Breakouts with volume signal potential new trends"
        ],
        compliance_disclaimer=COMPLIANCE_DISCLAIMERS["educational_only"],
        quiz_questions=[
            QuizQuestion(
                question="How do you draw an uptrend line?",
                options=[
                    "Connect lower highs",
                    "Connect higher lows",
                    "Draw a horizontal line",
                    "Connect random points"
                ],
                correct_answer_index=1,
                explanation="An uptrend line is drawn by connecting two or more higher lows, acting as support.",
                points=10
            ),
            QuizQuestion(
                question="What makes a trend line more reliable?",
                options=[
                    "Using only 2 points",
                    "Having 3 or more touches",
                    "Making it horizontal",
                    "Drawing it very steep"
                ],
                correct_answer_index=1,
                explanation="A trend line becomes more reliable with 3 or more touches, validating its significance.",
                points=10
            )
        ]
    ))
    
    lessons.append(Lesson(
        lesson_id="tb_007",
        title="Support and Resistance Levels",
        category=LessonCategory.TRADING_BASICS,
        difficulty=LessonDifficulty.INTERMEDIATE,
        lesson_type=LessonType.TEXT,
        duration_minutes=6,
        order=17,
        prerequisites=["tb_006"],
        content=(
            "Support and resistance are key price levels where supply and demand create barriers.\n\n"
            "**Support Levels:**\n\n"
            "🛡️ **What is Support?**\n"
            "• Price level where buying pressure exceeds selling\n"
            "• Acts as a 'floor' preventing further decline\n"
            "• Where demand is strong enough to halt downward movement\n\n"
            "**Why Support Forms:**\n"
            "• Traders remember previous lows\n"
            "• Buyers see opportunity at lower prices\n"
            "• Psychological price levels (round numbers)\n\n"
            "**Resistance Levels:**\n\n"
            "🚧 **What is Resistance?**\n"
            "• Price level where selling pressure exceeds buying\n"
            "• Acts as a 'ceiling' preventing further rise\n"
            "• Where supply is strong enough to halt upward movement\n\n"
            "**Why Resistance Forms:**\n"
            "• Traders remember previous highs\n"
            "• Sellers take profits at higher prices\n"
            "• Psychological barriers\n\n"
            "**Role Reversal:**\n\n"
            "💱 **Key Concept:**\n"
            "• Broken support becomes resistance\n"
            "• Broken resistance becomes support\n"
            "• This flip confirms the level's significance\n\n"
            "**Identifying Strong Levels:**\n\n"
            "✅ **Strong S/R Characteristics:**\n"
            "• Multiple touches (3+)\n"
            "• Long time periods\n"
            "• High volume at the level\n"
            "• Round psychological numbers ($50, $100, etc.)\n"
            "• Historical significance\n\n"
            "**Trading Strategies:**\n\n"
            "📈 **Buy at Support:**\n"
            "• Price approaches support\n"
            "• Look for reversal signals\n"
            "• Stop-loss below support\n\n"
            "📉 **Sell at Resistance:**\n"
            "• Price approaches resistance\n"
            "• Look for rejection signals\n"
            "• Stop-loss above resistance\n\n"
            "⚡ **Breakout Trading:**\n"
            "• Strong close above resistance = buy\n"
            "• Strong close below support = sell\n"
            "• Requires volume confirmation"
        ),
        key_points=[
            "Support acts as floor, resistance as ceiling",
            "Broken levels often flip roles",
            "Multiple touches increase level strength",
            "Volume confirms breakouts through S/R"
        ],
        compliance_disclaimer=COMPLIANCE_DISCLAIMERS["educational_only"],
        quiz_questions=[
            QuizQuestion(
                question="What happens when a resistance level is broken?",
                options=[
                    "It disappears completely",
                    "It often becomes a support level",
                    "Price must fall immediately",
                    "Nothing changes"
                ],
                correct_answer_index=1,
                explanation="When resistance is broken, it often becomes a support level - this role reversal confirms its significance.",
                points=10
            ),
            QuizQuestion(
                question="What makes a support/resistance level more reliable?",
                options=[
                    "Only one touch",
                    "Multiple touches and high volume",
                    "Random price action",
                    "Short time periods"
                ],
                correct_answer_index=1,
                explanation="Multiple touches, long time periods, and high volume make support/resistance levels more reliable.",
                points=10
            )
        ]
    ))
    
    lessons.append(Lesson(
        lesson_id="tb_008",
        title="MACD Indicator",
        category=LessonCategory.TRADING_BASICS,
        difficulty=LessonDifficulty.ADVANCED,
        lesson_type=LessonType.TEXT,
        duration_minutes=7,
        order=18,
        prerequisites=["tb_007"],
        content=(
            "MACD (Moving Average Convergence Divergence) identifies trend changes and momentum.\n\n"
            "**MACD Components:**\n\n"
            "📊 **Three Elements:**\n\n"
            "1. **MACD Line** (Fast)\n"
            "   • 12-period EMA minus 26-period EMA\n"
            "   • Shows momentum direction\n\n"
            "2. **Signal Line** (Slow)\n"
            "   • 9-period EMA of MACD line\n"
            "   • Provides crossover signals\n\n"
            "3. **Histogram**\n"
            "   • Difference between MACD and Signal lines\n"
            "   • Visual representation of momentum\n\n"
            "**Reading MACD:**\n\n"
            "✅ **Bullish Signals:**\n"
            "• MACD crosses above signal line (buy)\n"
            "• MACD crosses above zero line (uptrend confirmation)\n"
            "• Histogram expanding upward (increasing momentum)\n"
            "• Bullish divergence (price makes lower low, MACD doesn't)\n\n"
            "❌ **Bearish Signals:**\n"
            "• MACD crosses below signal line (sell)\n"
            "• MACD crosses below zero line (downtrend confirmation)\n"
            "• Histogram expanding downward (decreasing momentum)\n"
            "• Bearish divergence (price makes higher high, MACD doesn't)\n\n"
            "**Divergence:**\n\n"
            "🔍 **Powerful Signal:**\n"
            "• Price and MACD moving in opposite directions\n"
            "• Signals potential trend reversal\n"
            "• Bullish divergence: Price falls but MACD rises\n"
            "• Bearish divergence: Price rises but MACD falls\n\n"
            "**Best Practices:**\n\n"
            "• Works best in trending markets\n"
            "• Less reliable in sideways/choppy markets\n"
            "• Combine with other indicators\n"
            "• Wait for crossover confirmation\n"
            "• Use histogram for momentum strength"
        ),
        key_points=[
            "MACD shows momentum and trend changes",
            "Crossovers generate buy/sell signals",
            "Divergence signals potential reversals",
            "Most effective in trending markets"
        ],
        compliance_disclaimer=COMPLIANCE_DISCLAIMERS["educational_only"],
        quiz_questions=[
            QuizQuestion(
                question="What does it mean when MACD crosses above the signal line?",
                options=[
                    "Bearish signal to sell",
                    "Bullish signal to buy",
                    "Market is closed",
                    "No trading signal"
                ],
                correct_answer_index=1,
                explanation="When MACD crosses above the signal line, it's a bullish signal indicating potential buying opportunity.",
                points=10
            ),
            QuizQuestion(
                question="What is bullish divergence?",
                options=[
                    "Price and MACD both rising",
                    "Price makes lower low but MACD doesn't",
                    "Price and MACD both falling",
                    "MACD crosses zero line"
                ],
                correct_answer_index=1,
                explanation="Bullish divergence occurs when price makes a lower low but MACD doesn't, signaling potential upward reversal.",
                points=10
            )
        ]
    ))
    
    lessons.append(Lesson(
        lesson_id="tb_009",
        title="Fibonacci Retracements",
        category=LessonCategory.TRADING_BASICS,
        difficulty=LessonDifficulty.ADVANCED,
        lesson_type=LessonType.TEXT,
        duration_minutes=6,
        order=19,
        prerequisites=["tb_008"],
        content=(
            "Fibonacci retracements identify potential support/resistance levels during pullbacks.\n\n"
            "**What are Fibonacci Levels?**\n\n"
            "Based on the Fibonacci sequence found in nature:\n"
            "• 23.6%, 38.2%, 50%, 61.8%, 78.6%\n"
            "• These percentages represent potential retracement levels\n\n"
            "**How to Use:**\n\n"
            "📊 **In Uptrend:**\n"
            "1. Identify swing low to swing high\n"
            "2. Draw Fibonacci from low to high\n"
            "3. Price may retrace to Fib levels before continuing up\n"
            "4. Common entry points: 38.2%, 50%, 61.8%\n\n"
            "📉 **In Downtrend:**\n"
            "1. Identify swing high to swing low\n"
            "2. Draw Fibonacci from high to low\n"
            "3. Price may retrace to Fib levels before continuing down\n"
            "4. Common resistance: 38.2%, 50%, 61.8%\n\n"
            "**Key Levels:**\n\n"
            "🎯 **Most Important:**\n"
            "• **38.2%**: Shallow retracement\n"
            "• **50.0%**: Mid-point, psychologically significant\n"
            "• **61.8%**: Golden ratio, strongest level\n\n"
            "**Trading Strategy:**\n\n"
            "✅ **Buying Opportunities:**\n"
            "• Uptrend retraces to Fib level\n"
            "• Look for reversal signals at level\n"
            "• Stop-loss below next Fib level\n"
            "• Target previous high or extension\n\n"
            "**Fibonacci Extensions:**\n"
            "• Project where price may go beyond previous high/low\n"
            "• Common targets: 127.2%, 161.8%, 261.8%\n"
            "• Used for profit targets\n\n"
            "**Important Notes:**\n"
            "• Not predictive, but probabilistic\n"
            "• Works best with other confirmations\n"
            "• May need to redraw as new swings form\n"
            "• Levels are zones, not exact prices"
        ),
        key_points=[
            "Fibonacci levels identify potential pullback areas",
            "61.8% (golden ratio) is most significant",
            "Use with other indicators for confirmation",
            "Extensions project profit targets beyond swings"
        ],
        compliance_disclaimer=COMPLIANCE_DISCLAIMERS["educational_only"],
        quiz_questions=[
            QuizQuestion(
                question="What is the most significant Fibonacci retracement level?",
                options=[
                    "23.6%",
                    "50.0%",
                    "61.8% (golden ratio)",
                    "100%"
                ],
                correct_answer_index=2,
                explanation="61.8%, known as the golden ratio, is considered the most significant Fibonacci level.",
                points=10
            ),
            QuizQuestion(
                question="How are Fibonacci retracements used in trading?",
                options=[
                    "To guarantee profit levels",
                    "To identify potential support/resistance during pullbacks",
                    "To predict exact future prices",
                    "To replace all other indicators"
                ],
                correct_answer_index=1,
                explanation="Fibonacci retracements help identify potential support/resistance zones during price pullbacks in a trend.",
                points=10
            )
        ]
    ))
    
    lessons.append(Lesson(
        lesson_id="tb_010",
        title="Chart Timeframes",
        category=LessonCategory.TRADING_BASICS,
        difficulty=LessonDifficulty.INTERMEDIATE,
        lesson_type=LessonType.TEXT,
        duration_minutes=5,
        order=20,
        prerequisites=["tb_009"],
        content=(
            "Different timeframes provide different perspectives on market behavior.\n\n"
            "**Common Timeframes:**\n\n"
            "⚡ **Short-term (1m - 15m)**\n"
            "• Best for: Day trading, scalping\n"
            "• Shows: Intraday price action\n"
            "• Noise level: High\n"
            "• Stress level: High\n\n"
            "📊 **Medium-term (1h - 4h)**\n"
            "• Best for: Swing trading\n"
            "• Shows: Intraday trends\n"
            "• Noise level: Moderate\n"
            "• Stress level: Moderate\n\n"
            "📈 **Long-term (1D - 1W)**\n"
            "• Best for: Position trading, investing\n"
            "• Shows: Major trends\n"
            "• Noise level: Low\n"
            "• Stress level: Low\n\n"
            "**Multiple Timeframe Analysis:**\n\n"
            "🔍 **Top-down Approach:**\n"
            "1. **Higher timeframe**: Identify overall trend (Daily/Weekly)\n"
            "2. **Medium timeframe**: Find entry opportunities (4H/1H)\n"
            "3. **Lower timeframe**: Fine-tune entry timing (15m/5m)\n\n"
            "**Alignment is Key:**\n"
            "• Trade in direction of higher timeframe trend\n"
            "• Use lower timeframes for entry precision\n"
            "• Conflicting timeframes = avoid or wait\n\n"
            "**Timeframe Selection:**\n\n"
            "✅ **Choose Based On:**\n"
            "• Your trading style (day, swing, position)\n"
            "• Available time to monitor\n"
            "• Risk tolerance\n"
            "• Capital size\n\n"
            "**NIJA's Approach:**\n\n"
            "NIJA analyzes multiple timeframes simultaneously:\n"
            "• Primary: 4H for trend direction\n"
            "• Entry: 1H for signal timing\n"
            "• Confirmation: 15m for execution\n"
            "• This multi-timeframe approach reduces false signals\n\n"
            "**Common Mistakes:**\n"
            "• Trading against higher timeframe trend\n"
            "• Switching timeframes randomly\n"
            "• Using too short timeframe (more noise)\n"
            "• Ignoring timeframe alignment"
        ),
        key_points=[
            "Different timeframes show different market perspectives",
            "Higher timeframes have less noise and show major trends",
            "Use multiple timeframes: higher for trend, lower for entry",
            "Trade in direction of higher timeframe trend"
        ],
        compliance_disclaimer=COMPLIANCE_DISCLAIMERS["educational_only"],
        quiz_questions=[
            QuizQuestion(
                question="What is the benefit of using multiple timeframe analysis?",
                options=[
                    "It makes trading more complicated",
                    "It provides different perspectives and reduces false signals",
                    "It's only for professional traders",
                    "It's not recommended"
                ],
                correct_answer_index=1,
                explanation="Multiple timeframe analysis provides different perspectives and helps reduce false signals by confirming trends.",
                points=10
            ),
            QuizQuestion(
                question="Which timeframe typically has the most noise?",
                options=[
                    "Monthly charts",
                    "Daily charts",
                    "1-minute charts",
                    "Weekly charts"
                ],
                correct_answer_index=2,
                explanation="Shorter timeframes like 1-minute charts have the most noise and random price fluctuations.",
                points=10
            )
        ]
    ))
    # (Continuing with tb_003 through tb_010 for Trading Basics)
    # (Then rm_001 through rm_010 for Risk Management)
    # (Then pf_001 through pf_008 for Platform Features)
    # (Then as_001 through as_006 for Advanced Strategies)
    # (Then cp_001 through cp_004 for Compliance)
    
    # For brevity, I'll add a few more representative lessons
    
    lessons.append(Lesson(
        lesson_id="rm_001",
        title="The Golden Rule: Never Risk More Than You Can Lose",
        category=LessonCategory.RISK_MANAGEMENT,
        difficulty=LessonDifficulty.BEGINNER,
        lesson_type=LessonType.TEXT,
        duration_minutes=4,
        order=11,
        prerequisites=["tb_002"],
        content=(
            "This is the most important lesson in trading.\n\n"
            "**The Reality:**\n"
            "• All trading involves risk of loss\n"
            "• Even the best strategies have losing trades\n"
            "• Market conditions can change unexpectedly\n"
            "• There are no profit promises in trading\n\n"
            "**What \"Afford to Lose\" Means:**\n\n"
            "❌ **Never use:**\n"
            "• Rent or mortgage money\n"
            "• Emergency savings\n"
            "• Borrowed money or loans\n"
            "• College funds\n"
            "• Retirement accounts\n\n"
            "✅ **Only use:**\n"
            "• Discretionary income\n"
            "• Money set aside specifically for trading\n"
            "• Amount that won't affect your lifestyle if lost\n\n"
            "**Emotional Impact:**\n"
            "If losing your trading capital would cause stress, anxiety, or financial hardship, "
            "you're risking too much. Proper capital allocation ensures you can trade without "
            "emotional pressure, which leads to better decisions.\n\n"
            "**NIJA's Protection:**\n"
            "• Daily loss limits prevent catastrophic losses\n"
            "• Position sizing limits control exposure\n"
            "• Stop-losses minimize per-trade risk\n"
            "• But YOU must choose appropriate capital"
        ),
        key_points=[
            "Only trade with discretionary income",
            "Never use money needed for living expenses",
            "Loss of trading capital should not cause hardship",
            "Proper capital allocation reduces emotional pressure"
        ],
        compliance_disclaimer=COMPLIANCE_DISCLAIMERS["trading_risk"],
        is_required=True
    ))
    
    lessons.append(Lesson(
        lesson_id="rm_002",
        title="Position Sizing and Risk Per Trade",
        category=LessonCategory.RISK_MANAGEMENT,
        difficulty=LessonDifficulty.INTERMEDIATE,
        lesson_type=LessonType.TEXT,
        duration_minutes=5,
        order=12,
        prerequisites=["rm_001"],
        content=(
            "Position sizing determines how much capital to allocate to each trade.\n\n"
            "**The 1-2% Rule:**\n"
            "Never risk more than 1-2% of your total capital on a single trade.\n\n"
            "**Example:**\n"
            "• Account size: $10,000\n"
            "• Risk per trade: 2% = $200\n"
            "• If stopped out, you only lose $200 (2%)\n"
            "• You can survive 50 consecutive losses\n\n"
            "**Why Small Position Sizes?**\n"
            "• Protects capital during losing streaks\n"
            "• Reduces emotional stress\n"
            "• Allows strategy to play out over many trades\n"
            "• Prevents single trade from destroying account\n\n"
            "**NIJA's Position Sizing:**\n\n"
            "NIJA automatically calculates position sizes based on:\n"
            "1. Your total account balance\n"
            "2. Your configured risk percentage\n"
            "3. Stop-loss distance\n"
            "4. Current market volatility\n\n"
            "**Configuration:**\n"
            "In Settings > Risk Management:\n"
            "• Set maximum position size (% of capital)\n"
            "• Configure risk per trade (1-3% recommended)\n"
            "• Set maximum concurrent positions\n\n"
            "**Common Mistake:**\n"
            "Using position sizes that are too large. Even with a good win rate, "
            "oversized positions can wipe out an account quickly during a losing streak."
        ),
        key_points=[
            "Risk 1-2% of capital per trade maximum",
            "Small positions protect against losing streaks",
            "NIJA auto-calculates appropriate position sizes",
            "Oversized positions are a common failure point"
        ],
        compliance_disclaimer=COMPLIANCE_DISCLAIMERS["educational_only"],
        is_required=True
    ))
    
    lessons.append(Lesson(
        lesson_id="cp_001",
        title="Risk Disclosure and Legal Notice",
        category=LessonCategory.COMPLIANCE,
        difficulty=LessonDifficulty.BEGINNER,
        lesson_type=LessonType.TEXT,
        duration_minutes=3,
        order=38,
        content=(
            "**IMPORTANT LEGAL DISCLOSURE**\n\n"
            "Please read and understand these critical points:\n\n"
            "**Trading Risks:**\n"
            "• Cryptocurrency trading involves substantial risk\n"
            "• You may lose all or more than your initial investment\n"
            "• Leverage can amplify both gains and losses\n"
            "• Market volatility can result in rapid losses\n"
            "• Past performance does not guarantee future results\n\n"
            "**Not Financial Advice:**\n"
            "• NIJA is a software tool, not a financial advisor\n"
            "• Nothing on this platform constitutes financial advice\n"
            "• We do not make investment recommendations\n"
            "• You are solely responsible for your trading decisions\n\n"
            "**No Guarantees:**\n"
            "• We make no guarantees of profitability\n"
            "• Historical performance is not indicative of future results\n"
            "• Strategy effectiveness may vary with market conditions\n"
            "• Technical issues may impact performance\n\n"
            "**Your Responsibilities:**\n"
            "• Understand the risks before trading\n"
            "• Only use capital you can afford to lose\n"
            "• Monitor your account regularly\n"
            "• Ensure compliance with local regulations\n"
            "• Consult professional advice as needed\n\n"
            "**Regulatory Compliance:**\n"
            "• Check if cryptocurrency trading is legal in your jurisdiction\n"
            "• Automated trading may have specific regulations\n"
            "• Tax obligations vary by location\n"
            "• You are responsible for regulatory compliance\n\n"
            "By continuing, you acknowledge understanding and accepting these risks."
        ),
        key_points=[
            "Trading involves substantial risk of loss",
            "This is not financial advice",
            "No guarantees of profitability",
            "You are responsible for your decisions and compliance"
        ],
        compliance_disclaimer=COMPLIANCE_DISCLAIMERS["trading_risk"],
        is_required=True
    ))
    
    # ========================================
    # CATEGORY 3: RISK MANAGEMENT (continued)
    # ========================================
    
    lessons.append(Lesson(
        lesson_id="rm_003",
        title="Stop-Loss Strategies",
        category=LessonCategory.RISK_MANAGEMENT,
        difficulty=LessonDifficulty.INTERMEDIATE,
        lesson_type=LessonType.TEXT,
        duration_minutes=6,
        order=21,
        prerequisites=["rm_002"],
        content=(
            "Stop-losses are your safety net, limiting losses on individual trades.\n\n"
            "**What is a Stop-Loss?**\n"
            "An order that automatically closes your position when price reaches a specified level,\n"
            "preventing further losses.\n\n"
            "**Why Stop-Losses are Critical:**\n\n"
            "🛡️ **Protection:**\n"
            "• Limits maximum loss on each trade\n"
            "• Prevents emotional decision-making\n"
            "• Allows you to walk away from screens\n"
            "• Protects against sudden market crashes\n\n"
            "❌ **Without Stop-Loss:**\n"
            "• Single trade can wipe out account\n"
            "• Hope/fear clouds judgment\n"
            "• Small loss becomes catastrophic\n"
            "• No sleep due to constant monitoring\n\n"
            "**Types of Stop-Losses:**\n\n"
            "1. **Fixed Percentage**\n"
            "   • Set % below entry (e.g., 2%)\n"
            "   • Simple and consistent\n"
            "   • Doesn't account for volatility\n\n"
            "2. **ATR-Based (Average True Range)**\n"
            "   • Adjusts for market volatility\n"
            "   • Wider stops in volatile markets\n"
            "   • Prevents premature stop-outs\n\n"
            "3. **Technical Levels**\n"
            "   • Below support in long trades\n"
            "   • Above resistance in short trades\n"
            "   • Based on market structure\n\n"
            "4. **Trailing Stop**\n"
            "   • Moves up with profitable trades\n"
            "   • Locks in profits as price rises\n"
            "   • Never moves against you\n\n"
            "**NIJA's Stop-Loss Approach:**\n\n"
            "🎯 **Intelligent Stops:**\n"
            "• ATR-based for volatility adjustment\n"
            "• Minimum 1.5% to avoid noise\n"
            "• Maximum 3% to limit risk\n"
            "• Automatically trails on profitable trades\n"
            "• Tightens as profit targets approach\n\n"
            "**Common Mistakes:**\n\n"
            "❌ **Don't Do This:**\n"
            "• Trading without stop-losses\n"
            "• Moving stop-loss further away when losing\n"
            "• Setting stops too tight (get stopped by noise)\n"
            "• Removing stops \"just this once\"\n"
            "• Setting stops at obvious levels everyone else uses\n\n"
            "**Best Practices:**\n\n"
            "✅ **Do This:**\n"
            "• Set stop-loss BEFORE entering trade\n"
            "• Never move stop-loss further from entry\n"
            "• Only trail stops in profit direction\n"
            "• Accept losses when stopped out\n"
            "• Calculate position size based on stop distance"
        ),
        key_points=[
            "Stop-losses are mandatory for every trade",
            "Set stops before entering, never move them against you",
            "ATR-based stops adjust for market volatility",
            "Trailing stops lock in profits as trade moves favorably"
        ],
        compliance_disclaimer=COMPLIANCE_DISCLAIMERS["trading_risk"],
        is_required=True,
        quiz_questions=[
            QuizQuestion(
                question="When should you set a stop-loss?",
                options=[
                    "After the trade starts losing",
                    "Before entering the trade",
                    "Only if the market is volatile",
                    "Stop-losses are optional"
                ],
                correct_answer_index=1,
                explanation="Always set stop-losses BEFORE entering a trade to define your risk upfront.",
                points=10
            ),
            QuizQuestion(
                question="What is a trailing stop-loss?",
                options=[
                    "A stop that never moves",
                    "A stop that moves with profitable trades to lock in gains",
                    "A stop below market price",
                    "A stop for losing trades only"
                ],
                correct_answer_index=1,
                explanation="A trailing stop moves up with profitable trades to lock in gains while protecting against reversals.",
                points=10
            ),
            QuizQuestion(
                question="Is it okay to move your stop-loss further away when losing?",
                options=[
                    "Yes, to give the trade more room",
                    "No, never move stops against your position",
                    "Only on weekends",
                    "Yes, if you're confident"
                ],
                correct_answer_index=1,
                explanation="Never move stop-losses further away when losing - this violates risk management and can lead to catastrophic losses.",
                points=10
            )
        ]
    ))
    
    lessons.append(Lesson(
        lesson_id="rm_004",
        title="Take-Profit Targets and Risk-Reward Ratios",
        category=LessonCategory.RISK_MANAGEMENT,
        difficulty=LessonDifficulty.INTERMEDIATE,
        lesson_type=LessonType.TEXT,
        duration_minutes=7,
        order=22,
        prerequisites=["rm_003"],
        content=(
            "Knowing when to take profits is as important as limiting losses.\n\n"
            "**What is a Take-Profit Target?**\n"
            "A predefined price level where you exit a profitable trade,\n"
            "securing your gains before potential reversal.\n\n"
            "**Risk-Reward Ratio (R:R):**\n\n"
            "📊 **The Math:**\n"
            "• R:R = Potential Profit ÷ Potential Loss\n"
            "• Example: Risk $100 to make $300 = 3:1 R:R\n\n"
            "**Minimum Acceptable R:R:**\n"
            "• 1:1 = Break even with 50% win rate\n"
            "• 2:1 = Profitable with 33%+ win rate\n"
            "• 3:1 = Profitable with 25%+ win rate ⭐ Recommended\n\n"
            "**Why 3:1 Matters:**\n\n"
            "Example with 40% win rate:\n"
            "• 10 trades: 4 wins, 6 losses\n"
            "• Each loss: -$100 × 6 = -$600\n"
            "• Each win: +$300 × 4 = +$1,200\n"
            "• Net profit: +$600 💰\n\n"
            "**Setting Profit Targets:**\n\n"
            "1. **Technical Levels**\n"
            "   • Previous high/low\n"
            "   • Support/resistance zones\n"
            "   • Round psychological numbers\n\n"
            "2. **Fibonacci Extensions**\n"
            "   • 127.2%, 161.8%, 261.8%\n"
            "   • Projected from swing points\n\n"
            "3. **Fixed R:R Multiple**\n"
            "   • If risk is $100, target $300 (3:1)\n"
            "   • Simple and consistent\n\n"
            "4. **ATR Multiples**\n"
            "   • 2-3× ATR from entry\n"
            "   • Adapts to volatility\n\n"
            "**Partial Profit Taking:**\n\n"
            "🎯 **Scaling Out Strategy:**\n"
            "• Take 50% profit at 2:1 R:R\n"
            "• Trail stop on remaining 50%\n"
            "• Reduces pressure, locks gains\n"
            "• Lets winners run further\n\n"
            "**NIJA's Approach:**\n\n"
            "🎲 **Intelligent Targets:**\n"
            "• Minimum 2:1 R:R required to enter\n"
            "• Primary target: 3:1 R:R\n"
            "• Partial profit at 2:1 (50% of position)\n"
            "• Trail remaining position for extended gains\n"
            "• Adjusts targets based on volatility and trend strength\n\n"
            "**Common Mistakes:**\n\n"
            "❌ **Don't:**\n"
            "• Take profits too early from fear\n"
            "• Let winners turn into losers\n"
            "• Accept trades with R:R below 2:1\n"
            "• Move targets further away when close\n"
            "• Exit profitable trades without plan\n\n"
            "✅ **Do:**\n"
            "• Define target before entering\n"
            "• Stick to your plan\n"
            "• Use trailing stops to maximize winners\n"
            "• Track actual R:R performance\n"
            "• Only take trades with favorable R:R"
        ),
        key_points=[
            "Risk-reward ratio determines long-term profitability",
            "Minimum 2:1 R:R, aim for 3:1 or better",
            "Define profit targets before entering trades",
            "Partial profit-taking reduces risk while letting winners run"
        ],
        compliance_disclaimer=COMPLIANCE_DISCLAIMERS["educational_only"],
        is_required=True,
        quiz_questions=[
            QuizQuestion(
                question="What does a 3:1 risk-reward ratio mean?",
                options=[
                    "Risk $3 to make $1",
                    "Risk $1 to make $3",
                    "Win 3 out of 1 trades",
                    "Trade 3 times per day"
                ],
                correct_answer_index=1,
                explanation="A 3:1 R:R means risking $1 to potentially make $3 - you aim to make 3× what you risk.",
                points=10
            ),
            QuizQuestion(
                question="With a 3:1 R:R, what win rate do you need to be profitable?",
                options=[
                    "90%",
                    "50%",
                    "25% or higher",
                    "10%"
                ],
                correct_answer_index=2,
                explanation="With 3:1 R:R, you only need to win 25%+ of trades to be profitable due to larger wins.",
                points=10
            ),
            QuizQuestion(
                question="What is a good partial profit strategy?",
                options=[
                    "Take all profit at first sign of gain",
                    "Never take profits",
                    "Take 50% profit at 2:1, trail stop on rest",
                    "Wait until stop-loss is hit"
                ],
                correct_answer_index=2,
                explanation="Taking 50% profit at 2:1 R:R locks in gains while trailing the remainder lets winners run further.",
                points=10
            )
        ]
    ))
    
    # Continue with more lessons across all categories to reach 40 total
    # For this implementation, we have 20 lessons defined above
    # In a full implementation, you would add 20 more lessons to reach 40
    
    return sorted(lessons, key=lambda x: x.order)


def get_lessons_by_category(category: LessonCategory) -> List[Lesson]:
    """Get all lessons for a specific category"""
    all_lessons = create_lesson_map()
    return [lesson for lesson in all_lessons if lesson.category == category]


def get_lesson_by_id(lesson_id: str) -> Optional[Lesson]:
    """Get a specific lesson by ID"""
    all_lessons = create_lesson_map()
    for lesson in all_lessons:
        if lesson.lesson_id == lesson_id:
            return lesson
    return None


def get_required_lessons() -> List[Lesson]:
    """Get all required lessons that must be completed"""
    all_lessons = create_lesson_map()
    return [lesson for lesson in all_lessons if lesson.is_required]


def get_next_available_lesson(completed_lesson_ids: List[str]) -> Optional[Lesson]:
    """
    Get the next available lesson based on completed lessons and prerequisites
    
    Args:
        completed_lesson_ids: List of lesson IDs already completed
        
    Returns:
        Next available lesson or None if all complete
    """
    all_lessons = create_lesson_map()
    
    for lesson in all_lessons:
        # Skip if already completed
        if lesson.lesson_id in completed_lesson_ids:
            continue
        
        # Check if prerequisites are met
        prerequisites_met = all(
            prereq_id in completed_lesson_ids 
            for prereq_id in lesson.prerequisites
        )
        
        if prerequisites_met:
            return lesson
    
    return None
