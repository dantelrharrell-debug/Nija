#!/usr/bin/env python3
"""
NIJA Live User Status Summary
==============================

Provides a clean, real-time status report showing:
- User balances across all brokers
- Trading readiness status
- Open positions and P&L
- Risk status

This makes monitoring all users super easy with one clean report.

Usage:
    python user_status_summary.py
    python user_status_summary.py --detailed
    python user_status_summary.py --json
"""

import os
import sys
import logging
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
import argparse

# Configure logging
logging.basicConfig(
    level=logging.WARNING,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Import database models and connection
try:
    from database.db_connection import init_database, get_db_session, check_database_health
    from database.models import User, Position, BrokerCredential, TradingInstance
    DATABASE_AVAILABLE = True
except ImportError as e:
    logger.warning(f"Database imports not available: {e}")
    DATABASE_AVAILABLE = False

# Import controls and risk management
try:
    from controls import get_hard_controls
    CONTROLS_AVAILABLE = True
except ImportError as e:
    logger.warning(f"Controls not available: {e}")
    CONTROLS_AVAILABLE = False

# Import user risk manager
try:
    from bot.user_risk_manager import get_user_risk_manager
    RISK_MANAGER_AVAILABLE = True
except ImportError as e:
    logger.warning(f"User risk manager not available: {e}")
    RISK_MANAGER_AVAILABLE = False

# Import user PnL tracker for balance and stats
try:
    from bot.user_pnl_tracker import get_user_pnl_tracker
    PNL_TRACKER_AVAILABLE = True
except ImportError as e:
    logger.warning(f"User PnL tracker not available: {e}")
    PNL_TRACKER_AVAILABLE = False


@dataclass
class UserStatus:
    """Complete status for a single user"""
    user_id: str
    email: str = ""
    tier: str = "basic"
    enabled: bool = True
    
    # Trading instance status
    instance_status: str = "unknown"
    last_activity: Optional[datetime] = None
    
    # Balances
    total_balance_usd: float = 0.0
    broker_balances: Dict[str, float] = field(default_factory=dict)
    
    # Positions
    open_positions: int = 0
    total_position_value_usd: float = 0.0
    unrealized_pnl: float = 0.0
    
    # Trading readiness
    can_trade: bool = False
    trading_status_reason: str = ""
    
    # Risk status
    daily_pnl: float = 0.0
    circuit_breaker_triggered: bool = False
    risk_level: str = "unknown"
    
    # Brokers configured
    configured_brokers: List[str] = field(default_factory=list)


class UserStatusSummary:
    """Generate live status summary for all users"""
    
    def __init__(self):
        """Initialize status summary generator"""
        self.hard_controls = None
        self.risk_manager = None
        self.pnl_tracker = None
        
        # Initialize components if available
        if CONTROLS_AVAILABLE:
            self.hard_controls = get_hard_controls()
        
        if RISK_MANAGER_AVAILABLE:
            self.risk_manager = get_user_risk_manager()
        
        if PNL_TRACKER_AVAILABLE:
            self.pnl_tracker = get_user_pnl_tracker()
    
    def get_all_users(self) -> List[UserStatus]:
        """
        Get status for all users in the system
        
        Tries multiple sources:
        1. Database (preferred)
        2. Config files (fallback)
        
        Returns:
            List of UserStatus objects
        """
        users = []
        
        # Try database first
        if DATABASE_AVAILABLE:
            try:
                users = self._get_users_from_database()
                if users:
                    return users
            except Exception as e:
                logger.warning(f"Could not fetch users from database: {e}")
        
        # Fallback to config files
        try:
            users = self._get_users_from_config()
        except Exception as e:
            logger.warning(f"Could not fetch users from config: {e}")
        
        return users
    
    def _get_users_from_database(self) -> List[UserStatus]:
        """Get users from database"""
        users = []
        
        # Initialize database if needed
        try:
            init_database()
        except Exception as e:
            logger.debug(f"Database initialization error: {e}")
            return users
        
        # Query all users from database
        with get_db_session() as session:
            db_users = session.query(User).all()
            
            for db_user in db_users:
                user_status = self._build_user_status_from_db(session, db_user)
                users.append(user_status)
        
        return users
    
    def _get_users_from_config(self) -> List[UserStatus]:
        """Get users from config files (fallback when database unavailable)"""
        users = []
        
        try:
            from config import get_user_config_loader
            
            if get_user_config_loader is None or not callable(get_user_config_loader):
                return users
            
            loader = get_user_config_loader()
            enabled_users = loader.get_all_enabled_users()
            
            # Deduplicate by user_id
            seen_user_ids = set()
            for user_config in enabled_users:
                if user_config.user_id not in seen_user_ids:
                    seen_user_ids.add(user_config.user_id)
                    user_status = self._build_user_status_from_config(user_config)
                    users.append(user_status)
        
        except Exception as e:
            logger.debug(f"Error loading users from config: {e}")
        
        return users
    
    def _build_user_status_from_config(self, user_config) -> UserStatus:
        """Build user status from config file data"""
        user_status = UserStatus(
            user_id=user_config.user_id,
            email=getattr(user_config, 'email', ''),
            tier=getattr(user_config, 'tier', 'basic'),
            enabled=user_config.enabled
        )
        
        # Add configured broker
        if hasattr(user_config, 'broker'):
            user_status.configured_brokers.append(user_config.broker)
        
        # Get balance and status from risk manager
        if self.risk_manager:
            try:
                risk_state = self.risk_manager.get_state(user_config.user_id)
                user_status.total_balance_usd = risk_state.balance
                user_status.daily_pnl = risk_state.daily_pnl
                user_status.circuit_breaker_triggered = risk_state.circuit_breaker_triggered
                
                # Calculate risk level
                if user_status.total_balance_usd > 0:
                    daily_pnl_pct = (user_status.daily_pnl / user_status.total_balance_usd) * 100
                    if daily_pnl_pct < -5:
                        user_status.risk_level = "high"
                    elif daily_pnl_pct < -2:
                        user_status.risk_level = "medium"
                    elif daily_pnl_pct > 2:
                        user_status.risk_level = "profitable"
                    else:
                        user_status.risk_level = "normal"
            except Exception as e:
                logger.debug(f"Could not get risk state for {user_config.user_id}: {e}")
        
        # Check trading readiness
        if self.hard_controls:
            can_trade, reason = self.hard_controls.can_trade(user_config.user_id)
            user_status.can_trade = can_trade
            user_status.trading_status_reason = reason or "Ready to trade"
        
        return user_status
    
    def _build_user_status_from_db(self, session, db_user) -> UserStatus:
        """
        Build complete status for a single user
        
        Args:
            session: Database session
            db_user: User database model
            
        Returns:
            UserStatus object
        """
        user_status = UserStatus(
            user_id=db_user.user_id,
            email=db_user.email,
            tier=db_user.subscription_tier,
            enabled=db_user.enabled
        )
        
        # Get trading instance status
        if db_user.trading_instance:
            user_status.instance_status = db_user.trading_instance.status
            user_status.last_activity = db_user.trading_instance.last_activity
        
        # Get configured brokers
        user_status.configured_brokers = [
            cred.broker_name for cred in db_user.broker_credentials
        ]
        
        # Get balance from risk manager (more reliable than broker API calls)
        if self.risk_manager:
            try:
                risk_state = self.risk_manager.get_state(db_user.user_id)
                user_status.total_balance_usd = risk_state.balance
                
                # For now, attribute full balance to configured brokers
                # In the future, we can track per-broker balances
                if user_status.configured_brokers:
                    # Split balance equally across brokers as an approximation
                    # This is just for display purposes
                    per_broker = user_status.total_balance_usd / len(user_status.configured_brokers)
                    for broker_name in user_status.configured_brokers:
                        user_status.broker_balances[broker_name] = per_broker
            except Exception as e:
                logger.debug(f"Could not get balance from risk manager for {db_user.user_id}: {e}")
        
        # Try to get more accurate PnL data from tracker
        if self.pnl_tracker:
            try:
                stats = self.pnl_tracker.get_stats(db_user.user_id)
                if stats.get('balance'):
                    user_status.total_balance_usd = stats['balance']
            except Exception as e:
                logger.debug(f"Could not get stats from PnL tracker for {db_user.user_id}: {e}")
        
        # Get open positions
        open_positions = session.query(Position).filter(
            Position.user_id == db_user.user_id,
            Position.status == 'open'
        ).all()
        
        user_status.open_positions = len(open_positions)
        
        # Calculate unrealized P&L and position value
        for position in open_positions:
            if position.pnl:
                user_status.unrealized_pnl += float(position.pnl)
            if position.current_price and position.size:
                user_status.total_position_value_usd += float(position.current_price * position.size)
        
        # Check trading readiness
        if self.hard_controls:
            can_trade, reason = self.hard_controls.can_trade(db_user.user_id)
            user_status.can_trade = can_trade
            user_status.trading_status_reason = reason or "Ready to trade"
        
        # Get risk status
        if self.risk_manager:
            try:
                risk_state = self.risk_manager.get_state(db_user.user_id)
                user_status.daily_pnl = risk_state.daily_pnl
                user_status.circuit_breaker_triggered = risk_state.circuit_breaker_triggered
                
                # Determine risk level based on daily P&L
                if user_status.total_balance_usd > 0:
                    daily_pnl_pct = (user_status.daily_pnl / user_status.total_balance_usd) * 100
                    if daily_pnl_pct < -5:
                        user_status.risk_level = "high"
                    elif daily_pnl_pct < -2:
                        user_status.risk_level = "medium"
                    elif daily_pnl_pct > 2:
                        user_status.risk_level = "profitable"
                    else:
                        user_status.risk_level = "normal"
                else:
                    user_status.risk_level = "normal"
            except Exception as e:
                logger.warning(f"Could not get risk status for {db_user.user_id}: {e}")
        
        return user_status
    

    
    def print_summary(self, users: List[UserStatus], detailed: bool = False):
        """
        Print a clean, formatted summary of all users
        
        Args:
            users: List of UserStatus objects
            detailed: Include detailed information
        """
        print("\n" + "=" * 100)
        print("NIJA LIVE USER STATUS SUMMARY")
        print(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * 100)
        
        if not users:
            print("\n⚠️  No users found in the system")
            print("\nPossible reasons:")
            print("  - Database not configured")
            print("  - No users registered yet")
            print("  - Database connection failed")
            return
        
        # Summary statistics
        total_users = len(users)
        active_users = sum(1 for u in users if u.enabled)
        trading_users = sum(1 for u in users if u.can_trade)
        users_with_positions = sum(1 for u in users if u.open_positions > 0)
        total_balance = sum(u.total_balance_usd for u in users)
        total_unrealized_pnl = sum(u.unrealized_pnl for u in users)
        
        print(f"\n📊 PLATFORM OVERVIEW")
        print(f"   Total Users: {total_users}")
        print(f"   Active: {active_users} | Trading Ready: {trading_users} | With Positions: {users_with_positions}")
        print(f"   Total Capital: ${total_balance:,.2f}")
        print(f"   Total Unrealized P&L: ${total_unrealized_pnl:,.2f}")
        
        # Individual user status
        print(f"\n👥 USER STATUS")
        print("-" * 100)
        
        for user in sorted(users, key=lambda u: u.total_balance_usd, reverse=True):
            self._print_user_status(user, detailed)
        
        print("\n" + "=" * 100)
        
        # Legend
        print("\n📖 STATUS LEGEND")
        print("   ✅ Ready to trade | ⛔ Trading disabled")
        print("   💰 Has balance | 📈 Has open positions")
        print("   🔴 High risk | 🟡 Medium risk | 🟢 Normal | 💚 Profitable")
    
    def _print_user_status(self, user: UserStatus, detailed: bool):
        """Print status for a single user"""
        # Status indicators
        trade_icon = "✅" if user.can_trade else "⛔"
        balance_icon = "💰" if user.total_balance_usd > 0 else "  "
        position_icon = "📈" if user.open_positions > 0 else "  "
        
        # Risk level icon
        risk_icons = {
            "high": "🔴",
            "medium": "🟡",
            "normal": "🟢",
            "profitable": "💚",
            "unknown": "  "
        }
        risk_icon = risk_icons.get(user.risk_level, "  ")
        
        # Main status line
        print(f"\n{trade_icon} {balance_icon} {position_icon} {risk_icon} {user.user_id} ({user.tier})")
        
        # Balance info
        if user.total_balance_usd > 0 or user.broker_balances:
            if user.broker_balances:
                broker_info = " | ".join([
                    f"{broker}: ${bal:,.2f}" 
                    for broker, bal in user.broker_balances.items()
                ])
                print(f"      Balance: ${user.total_balance_usd:,.2f} ({broker_info})")
            else:
                print(f"      Balance: ${user.total_balance_usd:,.2f}")
        else:
            print(f"      Balance: No balance data available")
        
        # Position info
        if user.open_positions > 0:
            pnl_sign = "+" if user.unrealized_pnl >= 0 else ""
            print(f"      Positions: {user.open_positions} open | Unrealized P&L: {pnl_sign}${user.unrealized_pnl:,.2f}")
        
        # Trading status
        if not user.can_trade:
            print(f"      Status: ⛔ {user.trading_status_reason}")
        else:
            status_parts = []
            if user.instance_status == "running":
                status_parts.append("Running")
            if user.daily_pnl != 0:
                pnl_sign = "+" if user.daily_pnl >= 0 else ""
                status_parts.append(f"Daily P&L: {pnl_sign}${user.daily_pnl:,.2f}")
            if user.circuit_breaker_triggered:
                status_parts.append("⚠️ Circuit Breaker Active")
            
            if status_parts:
                print(f"      Status: {' | '.join(status_parts)}")
        
        # Detailed info
        if detailed:
            print(f"      Email: {user.email}")
            print(f"      Brokers: {', '.join(user.configured_brokers) if user.configured_brokers else 'None configured'}")
            if user.last_activity:
                print(f"      Last Activity: {user.last_activity.strftime('%Y-%m-%d %H:%M:%S')}")
    
    def get_summary_dict(self, users: List[UserStatus]) -> Dict:
        """
        Get summary as a dictionary (for JSON output)
        
        Args:
            users: List of UserStatus objects
            
        Returns:
            Dictionary with summary data
        """
        return {
            'timestamp': datetime.now().isoformat(),
            'platform_overview': {
                'total_users': len(users),
                'active_users': sum(1 for u in users if u.enabled),
                'trading_ready': sum(1 for u in users if u.can_trade),
                'users_with_positions': sum(1 for u in users if u.open_positions > 0),
                'total_capital_usd': sum(u.total_balance_usd for u in users),
                'total_unrealized_pnl': sum(u.unrealized_pnl for u in users)
            },
            'users': [
                {
                    'user_id': u.user_id,
                    'email': u.email,
                    'tier': u.tier,
                    'enabled': u.enabled,
                    'can_trade': u.can_trade,
                    'trading_status': u.trading_status_reason,
                    'instance_status': u.instance_status,
                    'total_balance_usd': u.total_balance_usd,
                    'broker_balances': u.broker_balances,
                    'open_positions': u.open_positions,
                    'unrealized_pnl': u.unrealized_pnl,
                    'daily_pnl': u.daily_pnl,
                    'risk_level': u.risk_level,
                    'circuit_breaker': u.circuit_breaker_triggered,
                    'configured_brokers': u.configured_brokers,
                    'last_activity': u.last_activity.isoformat() if u.last_activity else None
                }
                for u in users
            ]
        }


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description='NIJA Live User Status Summary - Monitor all users in one clean report'
    )
    parser.add_argument(
        '--detailed',
        action='store_true',
        help='Show detailed information for each user'
    )
    parser.add_argument(
        '--json',
        action='store_true',
        help='Output as JSON instead of formatted text'
    )
    parser.add_argument(
        '--quiet',
        action='store_true',
        help='Suppress warnings and info messages'
    )
    
    args = parser.parse_args()
    
    # Set logging level
    if args.quiet or args.json:
        logging.getLogger().setLevel(logging.ERROR)
    
    # Check database health first
    if DATABASE_AVAILABLE and not args.json:
        try:
            init_database()
            health = check_database_health()
            if not health.get('healthy'):
                print(f"\n⚠️  Warning: Database health check failed: {health.get('error')}", file=sys.stderr)
                print("Some features may not be available.\n", file=sys.stderr)
        except Exception as e:
            print(f"\n⚠️  Warning: Could not initialize database: {e}", file=sys.stderr)
            print("Some features may not be available.\n", file=sys.stderr)
    
    # Generate summary
    summary = UserStatusSummary()
    users = summary.get_all_users()
    
    # Output
    if args.json:
        import json
        summary_dict = summary.get_summary_dict(users)
        print(json.dumps(summary_dict, indent=2))
    else:
        summary.print_summary(users, detailed=args.detailed)


if __name__ == "__main__":
    main()
