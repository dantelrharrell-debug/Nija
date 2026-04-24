"""
NIJA Mobile App - Interactive Tutorial Scripts

Provides step-by-step interactive tutorials and walkthroughs for key app features.
Includes tooltips, overlays, and guided tours.

Author: NIJA Trading Systems
Version: 1.0
Date: January 31, 2026
"""

from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from enum import Enum


class TutorialType(Enum):
    """Types of tutorials available"""
    ONBOARDING = "onboarding"  # First-time user onboarding
    FEATURE_INTRO = "feature_intro"  # Introduction to a specific feature
    WORKFLOW = "workflow"  # Complete workflow walkthrough
    TOOLTIP = "tooltip"  # Single-step contextual help


class TutorialTrigger(Enum):
    """When the tutorial should be triggered"""
    ON_FIRST_LAUNCH = "on_first_launch"
    ON_FEATURE_ACCESS = "on_feature_access"
    MANUAL = "manual"
    ON_ERROR = "on_error"


class StepAction(Enum):
    """Actions the user must take to complete a step"""
    TAP = "tap"
    SWIPE = "swipe"
    SCROLL = "scroll"
    INPUT = "input"
    TOGGLE = "toggle"
    READ = "read"
    WAIT = "wait"


@dataclass
class TutorialStep:
    """A single step in a tutorial"""
    step_id: str
    title: str
    description: str
    target_element: Optional[str] = None  # Element ID to highlight
    action_required: StepAction = StepAction.READ
    validation_criteria: Optional[str] = None  # How to verify step completion
    overlay_position: str = "bottom"  # top, bottom, left, right, center
    show_hand_pointer: bool = False
    allow_skip: bool = True
    timeout_seconds: Optional[int] = None
    image_url: Optional[str] = None
    video_url: Optional[str] = None


@dataclass
class Tutorial:
    """Complete tutorial definition"""
    tutorial_id: str
    name: str
    description: str
    tutorial_type: TutorialType
    trigger: TutorialTrigger
    steps: List[TutorialStep]
    prerequisites: List[str] = field(default_factory=list)
    estimated_duration_minutes: int = 5
    category: str = "general"
    is_required: bool = False
    show_progress_bar: bool = True


def create_tutorial_library() -> List[Tutorial]:
    """
    Create the complete library of interactive tutorials
    
    Returns:
        List of Tutorial objects
    """
    tutorials = []
    
    # =========================================
    # ONBOARDING TUTORIALS
    # =========================================
    
    tutorials.append(Tutorial(
        tutorial_id="onboard_welcome",
        name="Welcome to NIJA",
        description="Quick introduction to the app",
        tutorial_type=TutorialType.ONBOARDING,
        trigger=TutorialTrigger.ON_FIRST_LAUNCH,
        estimated_duration_minutes=2,
        category="onboarding",
        is_required=True,
        steps=[
            TutorialStep(
                step_id="welcome_1",
                title="Welcome!",
                description=(
                    "👋 Welcome to NIJA - your intelligent cryptocurrency trading assistant!\n\n"
                    "This quick tour will show you around the app. Ready to start?"
                ),
                action_required=StepAction.TAP,
                overlay_position="center",
                allow_skip=False
            ),
            TutorialStep(
                step_id="welcome_2",
                title="Your Dashboard",
                description=(
                    "This is your dashboard - your trading command center.\n\n"
                    "Here you'll see:\n"
                    "• Portfolio value and P&L\n"
                    "• Active trading positions\n"
                    "• Recent trades\n"
                    "• Performance stats"
                ),
                target_element="dashboard_overview",
                action_required=StepAction.READ,
                overlay_position="bottom"
            ),
            TutorialStep(
                step_id="welcome_3",
                title="Trading Control",
                description=(
                    "This toggle controls trading.\n\n"
                    "🟢 ON: Bot is actively trading\n"
                    "🔴 OFF: Bot is paused\n\n"
                    "You can turn it on/off anytime with a single tap."
                ),
                target_element="trading_toggle",
                action_required=StepAction.READ,
                overlay_position="bottom",
                show_hand_pointer=True
            ),
            TutorialStep(
                step_id="welcome_4",
                title="Navigation Menu",
                description=(
                    "Tap the menu icon to access:\n"
                    "• Settings and risk controls\n"
                    "• Trade history\n"
                    "• Performance analytics\n"
                    "• Education center\n"
                    "• Help and support"
                ),
                target_element="menu_button",
                action_required=StepAction.TAP,
                overlay_position="top",
                show_hand_pointer=True
            ),
            TutorialStep(
                step_id="welcome_5",
                title="Education First!",
                description=(
                    "Before you start trading, we strongly recommend completing the "
                    "educational lessons.\n\n"
                    "Learn about:\n"
                    "• How automated trading works\n"
                    "• Risk management essentials\n"
                    "• Platform features\n\n"
                    "Ready to learn? Tap 'Start Learning' to begin!"
                ),
                action_required=StepAction.TAP,
                overlay_position="center",
                allow_skip=True
            )
        ]
    ))
    
    tutorials.append(Tutorial(
        tutorial_id="onboard_first_trade",
        name="Your First Trade Setup",
        description="Step-by-step guide to configuring your first trade",
        tutorial_type=TutorialType.WORKFLOW,
        trigger=TutorialTrigger.MANUAL,
        estimated_duration_minutes=5,
        category="onboarding",
        is_required=False,
        prerequisites=["onboard_welcome"],
        steps=[
            TutorialStep(
                step_id="first_trade_1",
                title="Connect Your Exchange",
                description=(
                    "First, you need to connect your exchange account.\n\n"
                    "1. Go to Settings > Exchange Connection\n"
                    "2. Select your exchange (Coinbase, Kraken, etc.)\n"
                    "3. Enter your API keys\n\n"
                    "Don't have API keys yet? Tap 'Learn How' for a guide."
                ),
                target_element="settings_menu",
                action_required=StepAction.TAP,
                overlay_position="right"
            ),
            TutorialStep(
                step_id="first_trade_2",
                title="Set Risk Limits",
                description=(
                    "Configure your risk parameters:\n\n"
                    "• Maximum position size (start with 1-2% of capital)\n"
                    "• Daily loss limit (recommended: 5%)\n"
                    "• Risk per trade (recommended: 1-2%)\n\n"
                    "These protect your capital from large losses."
                ),
                target_element="risk_settings",
                action_required=StepAction.INPUT,
                overlay_position="bottom"
            ),
            TutorialStep(
                step_id="first_trade_3",
                title="Review Strategy Settings",
                description=(
                    "NIJA uses a proven dual-RSI strategy.\n\n"
                    "Default settings are optimized for most users, but you can "
                    "customize:\n"
                    "• RSI thresholds\n"
                    "• Position holding time\n"
                    "• Profit targets\n\n"
                    "We recommend starting with defaults."
                ),
                target_element="strategy_settings",
                action_required=StepAction.READ,
                overlay_position="bottom"
            ),
            TutorialStep(
                step_id="first_trade_4",
                title="Test Mode First",
                description=(
                    "Before live trading, try TEST MODE:\n\n"
                    "• Simulates real trades\n"
                    "• No real money at risk\n"
                    "• See how the bot performs\n"
                    "• Get comfortable with the interface\n\n"
                    "Enable test mode in Settings."
                ),
                target_element="test_mode_toggle",
                action_required=StepAction.TOGGLE,
                overlay_position="bottom",
                show_hand_pointer=True
            ),
            TutorialStep(
                step_id="first_trade_5",
                title="Start Trading!",
                description=(
                    "You're all set! To start trading:\n\n"
                    "1. Return to dashboard\n"
                    "2. Toggle trading ON\n"
                    "3. Monitor your first positions\n\n"
                    "The bot will:\n"
                    "• Scan markets automatically\n"
                    "• Execute trades when signals appear\n"
                    "• Manage positions according to your risk rules\n\n"
                    "You'll get notifications for all trades."
                ),
                action_required=StepAction.READ,
                overlay_position="center"
            )
        ]
    ))
    
    # =========================================
    # FEATURE INTRODUCTION TUTORIALS
    # =========================================
    
    tutorials.append(Tutorial(
        tutorial_id="feature_positions",
        name="Understanding Positions",
        description="Learn about active positions and how to manage them",
        tutorial_type=TutorialType.FEATURE_INTRO,
        trigger=TutorialTrigger.ON_FEATURE_ACCESS,
        estimated_duration_minutes=3,
        category="features",
        steps=[
            TutorialStep(
                step_id="positions_1",
                title="Active Positions",
                description=(
                    "An 'active position' is a trade that's currently open.\n\n"
                    "Each position shows:\n"
                    "• Cryptocurrency pair (e.g., BTC-USD)\n"
                    "• Entry price (where you bought)\n"
                    "• Current price\n"
                    "• Profit/Loss (P&L) in real-time\n"
                    "• Position size (how much invested)"
                ),
                target_element="positions_list",
                action_required=StepAction.READ,
                overlay_position="bottom"
            ),
            TutorialStep(
                step_id="positions_2",
                title="Position Colors",
                description=(
                    "Positions are color-coded:\n\n"
                    "🟢 Green: Position is profitable\n"
                    "🔴 Red: Position has a loss\n"
                    "🟡 Yellow: Close to break-even\n\n"
                    "The bot automatically manages exits based on your strategy."
                ),
                action_required=StepAction.READ,
                overlay_position="center"
            ),
            TutorialStep(
                step_id="positions_3",
                title="Position Details",
                description=(
                    "Tap any position to see details:\n\n"
                    "• Full trade history\n"
                    "• Current P&L percentage\n"
                    "• Stop-loss level\n"
                    "• Target price\n"
                    "• Time in position\n\n"
                    "Try tapping a position now!"
                ),
                target_element="position_card",
                action_required=StepAction.TAP,
                overlay_position="bottom",
                show_hand_pointer=True
            ),
            TutorialStep(
                step_id="positions_4",
                title="Manual Close (Advanced)",
                description=(
                    "Normally, the bot manages exits automatically.\n\n"
                    "But you CAN manually close a position:\n"
                    "1. Tap the position\n"
                    "2. Tap 'Close Position'\n"
                    "3. Confirm\n\n"
                    "⚠️ Only do this if you have a specific reason - the bot's "
                    "automated exits are usually better!"
                ),
                action_required=StepAction.READ,
                overlay_position="center"
            )
        ]
    ))
    
    tutorials.append(Tutorial(
        tutorial_id="feature_notifications",
        name="Notification System",
        description="Configure and understand trade notifications",
        tutorial_type=TutorialType.FEATURE_INTRO,
        trigger=TutorialTrigger.MANUAL,
        estimated_duration_minutes=2,
        category="features",
        steps=[
            TutorialStep(
                step_id="notif_1",
                title="Stay Informed",
                description=(
                    "NIJA sends notifications for important events:\n\n"
                    "📈 Trade Entries: When a new position opens\n"
                    "📉 Trade Exits: When a position closes\n"
                    "⚠️ Risk Alerts: When approaching limits\n"
                    "💰 Profit Milestones: Daily/weekly targets\n"
                    "🔧 System Status: Connection issues, etc."
                ),
                action_required=StepAction.READ,
                overlay_position="center"
            ),
            TutorialStep(
                step_id="notif_2",
                title="Customize Notifications",
                description=(
                    "Control what notifications you receive:\n\n"
                    "Settings > Notifications\n\n"
                    "You can enable/disable:\n"
                    "• Every trade entry/exit\n"
                    "• Only profitable exits\n"
                    "• Daily summaries instead\n"
                    "• Alert thresholds\n\n"
                    "Find your preference!"
                ),
                target_element="notification_settings",
                action_required=StepAction.READ,
                overlay_position="bottom"
            ),
            TutorialStep(
                step_id="notif_3",
                title="Quiet Hours",
                description=(
                    "Don't want notifications while sleeping?\n\n"
                    "Enable 'Quiet Hours' to pause notifications during specific times.\n\n"
                    "The bot still trades - you just won't be disturbed.\n\n"
                    "Configure in Settings > Notifications > Quiet Hours"
                ),
                action_required=StepAction.READ,
                overlay_position="center"
            )
        ]
    ))
    
    tutorials.append(Tutorial(
        tutorial_id="feature_analytics",
        name="Performance Analytics",
        description="Understand your trading performance metrics",
        tutorial_type=TutorialType.FEATURE_INTRO,
        trigger=TutorialTrigger.ON_FEATURE_ACCESS,
        estimated_duration_minutes=4,
        category="features",
        steps=[
            TutorialStep(
                step_id="analytics_1",
                title="Performance Dashboard",
                description=(
                    "Your analytics dashboard shows comprehensive performance data.\n\n"
                    "Key metrics tracked:\n"
                    "• Total P&L (all-time profit/loss)\n"
                    "• Win rate (% of profitable trades)\n"
                    "• Average profit per trade\n"
                    "• Sharpe ratio (risk-adjusted returns)\n"
                    "• Maximum drawdown"
                ),
                target_element="analytics_dashboard",
                action_required=StepAction.READ,
                overlay_position="bottom"
            ),
            TutorialStep(
                step_id="analytics_2",
                title="Time Period Filters",
                description=(
                    "View performance over different periods:\n\n"
                    "• Today\n"
                    "• This Week\n"
                    "• This Month\n"
                    "• All Time\n"
                    "• Custom Range\n\n"
                    "Tap the filter to change time period."
                ),
                target_element="time_filter",
                action_required=StepAction.TAP,
                overlay_position="top",
                show_hand_pointer=True
            ),
            TutorialStep(
                step_id="analytics_3",
                title="Trade Distribution",
                description=(
                    "See how your trades are distributed:\n\n"
                    "📊 Win/Loss Chart: Visual breakdown\n"
                    "💎 Best Trades: Your biggest winners\n"
                    "📉 Worst Trades: Your biggest losers\n\n"
                    "Understanding this helps you optimize strategy settings."
                ),
                action_required=StepAction.SCROLL,
                overlay_position="center"
            ),
            TutorialStep(
                step_id="analytics_4",
                title="Export Reports",
                description=(
                    "Need data for taxes or records?\n\n"
                    "Export your trading history:\n"
                    "• PDF summary report\n"
                    "• CSV for spreadsheets\n"
                    "• Tax report format\n\n"
                    "Tap 'Export' in the top-right corner."
                ),
                target_element="export_button",
                action_required=StepAction.READ,
                overlay_position="left"
            )
        ]
    ))
    
    # =========================================
    # WORKFLOW TUTORIALS
    # =========================================
    
    tutorials.append(Tutorial(
        tutorial_id="workflow_risk_adjustment",
        name="Adjusting Risk Settings",
        description="How to safely modify your risk parameters",
        tutorial_type=TutorialType.WORKFLOW,
        trigger=TutorialTrigger.MANUAL,
        estimated_duration_minutes=3,
        category="workflows",
        steps=[
            TutorialStep(
                step_id="risk_adj_1",
                title="When to Adjust Risk",
                description=(
                    "You might adjust risk settings when:\n\n"
                    "• Starting with real money (reduce risk)\n"
                    "• Gaining confidence (gradually increase)\n"
                    "• Market volatility changes\n"
                    "• Your financial situation changes\n\n"
                    "⚠️ Never increase risk during a losing streak!"
                ),
                action_required=StepAction.READ,
                overlay_position="center"
            ),
            TutorialStep(
                step_id="risk_adj_2",
                title="Access Risk Settings",
                description=(
                    "To modify risk settings:\n\n"
                    "1. Open menu (☰)\n"
                    "2. Tap 'Settings'\n"
                    "3. Tap 'Risk Management'\n\n"
                    "You'll need to enter your password for security."
                ),
                target_element="menu_button",
                action_required=StepAction.TAP,
                overlay_position="top",
                show_hand_pointer=True,
                validation_criteria="navigated_to_risk_settings"
            ),
            TutorialStep(
                step_id="risk_adj_3",
                title="Key Risk Parameters",
                description=(
                    "Main settings to consider:\n\n"
                    "1. Position Size: Max % of capital per trade (1-5%)\n"
                    "2. Daily Loss Limit: Max loss before stopping (5-10%)\n"
                    "3. Max Concurrent Positions: How many trades at once (3-8)\n\n"
                    "Start conservative, increase gradually."
                ),
                action_required=StepAction.READ,
                overlay_position="bottom"
            ),
            TutorialStep(
                step_id="risk_adj_4",
                title="Save and Confirm",
                description=(
                    "After adjusting:\n\n"
                    "1. Review changes carefully\n"
                    "2. Tap 'Save Changes'\n"
                    "3. Confirm with password\n\n"
                    "Changes take effect immediately for new trades.\n"
                    "Existing positions use old settings until closed."
                ),
                action_required=StepAction.READ,
                overlay_position="center"
            )
        ]
    ))
    
    # =========================================
    # TOOLTIP/CONTEXTUAL HELP
    # =========================================
    
    tutorials.append(Tutorial(
        tutorial_id="tooltip_win_rate",
        name="Understanding Win Rate",
        description="What win rate means and why it matters",
        tutorial_type=TutorialType.TOOLTIP,
        trigger=TutorialTrigger.MANUAL,
        estimated_duration_minutes=1,
        category="tooltips",
        show_progress_bar=False,
        steps=[
            TutorialStep(
                step_id="winrate_tip",
                title="Win Rate Explained",
                description=(
                    "**Win Rate** = Percentage of trades that are profitable\n\n"
                    "Example: 60% win rate means 6 out of 10 trades profit.\n\n"
                    "Good win rates vary by strategy:\n"
                    "• 50-60%: Typical for trend-following\n"
                    "• 60-70%: Good\n"
                    "• 70%+: Excellent (but verify over many trades)\n\n"
                    "⚠️ Win rate alone doesn't guarantee profitability - average profit "
                    "per win vs. loss also matters!"
                ),
                action_required=StepAction.READ,
                overlay_position="bottom",
                allow_skip=False
            )
        ]
    ))
    
    tutorials.append(Tutorial(
        tutorial_id="tooltip_sharpe_ratio",
        name="Understanding Sharpe Ratio",
        description="Risk-adjusted return metric explanation",
        tutorial_type=TutorialType.TOOLTIP,
        trigger=TutorialTrigger.MANUAL,
        estimated_duration_minutes=1,
        category="tooltips",
        show_progress_bar=False,
        steps=[
            TutorialStep(
                step_id="sharpe_tip",
                title="Sharpe Ratio Explained",
                description=(
                    "**Sharpe Ratio** measures risk-adjusted returns.\n\n"
                    "Higher = Better returns relative to risk taken\n\n"
                    "Rule of thumb:\n"
                    "• < 1.0: Not great\n"
                    "• 1.0-2.0: Good\n"
                    "• 2.0-3.0: Very good\n"
                    "• 3.0+: Excellent\n\n"
                    "Formula: (Return - Risk-Free Rate) / Volatility\n\n"
                    "It's better to have consistent small wins (higher Sharpe) than "
                    "volatile big swings."
                ),
                action_required=StepAction.READ,
                overlay_position="bottom"
            )
        ]
    ))
    
    return tutorials


def get_tutorial_by_id(tutorial_id: str) -> Optional[Tutorial]:
    """Get a specific tutorial by ID"""
    for tutorial in create_tutorial_library():
        if tutorial.tutorial_id == tutorial_id:
            return tutorial
    return None


def get_tutorials_by_category(category: str) -> List[Tutorial]:
    """Get all tutorials for a specific category"""
    return [t for t in create_tutorial_library() if t.category == category]


def get_required_tutorials() -> List[Tutorial]:
    """Get all required tutorials that must be completed"""
    return [t for t in create_tutorial_library() if t.is_required]


def get_tutorials_by_trigger(trigger: TutorialTrigger) -> List[Tutorial]:
    """Get tutorials that match a specific trigger condition"""
    return [t for t in create_tutorial_library() if t.trigger == trigger]


@dataclass
class TutorialProgress:
    """Track user progress through a tutorial"""
    tutorial_id: str
    user_id: str
    started_at: datetime
    current_step_index: int = 0
    completed_steps: List[str] = field(default_factory=list)
    skipped: bool = False
    completed_at: Optional[datetime] = None
    
    def get_progress_percentage(self, tutorial: Tutorial) -> float:
        """Calculate completion percentage"""
        if not tutorial.steps:
            return 100.0
        return (len(self.completed_steps) / len(tutorial.steps)) * 100


class TutorialManager:
    """Manages tutorial state and progression"""
    
    def __init__(self):
        self.user_progress: Dict[str, Dict[str, TutorialProgress]] = {}
    
    def start_tutorial(self, user_id: str, tutorial_id: str) -> TutorialProgress:
        """Start a tutorial for a user"""
        if user_id not in self.user_progress:
            self.user_progress[user_id] = {}
        
        from datetime import datetime
        progress = TutorialProgress(
            tutorial_id=tutorial_id,
            user_id=user_id,
            started_at=datetime.now()
        )
        
        self.user_progress[user_id][tutorial_id] = progress
        return progress
    
    def complete_step(self, user_id: str, tutorial_id: str, step_id: str) -> bool:
        """Mark a tutorial step as completed"""
        if user_id not in self.user_progress:
            return False
        
        if tutorial_id not in self.user_progress[user_id]:
            return False
        
        progress = self.user_progress[user_id][tutorial_id]
        
        if step_id not in progress.completed_steps:
            progress.completed_steps.append(step_id)
            progress.current_step_index += 1
        
        # Check if tutorial is complete
        tutorial = get_tutorial_by_id(tutorial_id)
        if tutorial and len(progress.completed_steps) >= len(tutorial.steps):
            from datetime import datetime
            progress.completed_at = datetime.now()
        
        return True
    
    def skip_tutorial(self, user_id: str, tutorial_id: str):
        """Mark a tutorial as skipped"""
        if user_id not in self.user_progress:
            return
        
        if tutorial_id not in self.user_progress[user_id]:
            return
        
        progress = self.user_progress[user_id][tutorial_id]
        progress.skipped = True
        from datetime import datetime
        progress.completed_at = datetime.now()
    
    def get_progress(self, user_id: str, tutorial_id: str) -> Optional[TutorialProgress]:
        """Get user's progress for a specific tutorial"""
        if user_id not in self.user_progress:
            return None
        return self.user_progress[user_id].get(tutorial_id)
    
    def has_completed_tutorial(self, user_id: str, tutorial_id: str) -> bool:
        """Check if user has completed a tutorial"""
        progress = self.get_progress(user_id, tutorial_id)
        return progress is not None and progress.completed_at is not None


# Global instance
_tutorial_manager = None


def get_tutorial_manager() -> TutorialManager:
    """Get the global tutorial manager instance"""
    global _tutorial_manager
    if _tutorial_manager is None:
        _tutorial_manager = TutorialManager()
    return _tutorial_manager
