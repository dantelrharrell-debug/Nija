#!/usr/bin/env python3
"""
NIJA Control Center - Interactive CLI Launcher
===============================================

A comprehensive command-line control center for monitoring and managing NIJA trading bot.

Features:
- Live account balances and positions across all users/brokers
- Real-time P&L and performance metrics
- Trading status and alerts
- Quick action commands (emergency stop, pause trading, etc.)
- System health monitoring
- Interactive menu with auto-refresh

Usage:
    python nija_control_center.py
    python nija_control_center.py --refresh-interval 5
    python nija_control_center.py --detailed

Author: NIJA Trading Systems
Version: 1.0
Date: February 7, 2026
"""

import os
import sys
import time
import logging
import argparse
import json
from datetime import datetime
from typing import Dict, List, Optional, Any
from pathlib import Path
import subprocess

# Configure logging
logging.basicConfig(
    level=logging.WARNING,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Add bot directory to path
sys.path.insert(0, str(Path(__file__).parent))

# Import existing modules
try:
    from database.db_connection import init_database, get_db_session, check_database_health
    from database.models import User, Position, BrokerCredential
    DATABASE_AVAILABLE = True
except ImportError as e:
    logger.warning(f"Database not available: {e}")
    DATABASE_AVAILABLE = False

try:
    from controls import get_hard_controls
    CONTROLS_AVAILABLE = True
except ImportError:
    CONTROLS_AVAILABLE = False

try:
    from bot.user_pnl_tracker import get_user_pnl_tracker
    PNL_TRACKER_AVAILABLE = True
except ImportError:
    PNL_TRACKER_AVAILABLE = False

try:
    from bot.user_risk_manager import get_user_risk_manager
    RISK_MANAGER_AVAILABLE = True
except ImportError:
    RISK_MANAGER_AVAILABLE = False

try:
    from bot.broker_manager import BrokerManager
    BROKER_MANAGER_AVAILABLE = True
except ImportError:
    BROKER_MANAGER_AVAILABLE = False


class Colors:
    """ANSI color codes for terminal output"""
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKCYAN = '\033[96m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'


class NIJAControlCenter:
    """Main control center class"""

    def __init__(self, refresh_interval: int = 10, detailed: bool = False):
        self.refresh_interval = refresh_interval
        self.detailed = detailed
        self.running = False
        self.last_update = None
        
    def clear_screen(self):
        """Clear terminal screen"""
        os.system('clear' if os.name == 'posix' else 'cls')
        
    def print_header(self):
        """Print dashboard header"""
        print(f"{Colors.BOLD}{Colors.HEADER}")
        print("=" * 100)
        print("NIJA CONTROL CENTER - Live Trading Dashboard".center(100))
        print("=" * 100)
        print(f"{Colors.ENDC}")
        print(f"Last Updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print()

    def get_platform_overview(self) -> Dict[str, Any]:
        """Get platform-wide overview"""
        overview = {
            'total_users': 0,
            'active_users': 0,
            'total_capital': 0.0,
            'total_positions': 0,
            'unrealized_pnl': 0.0,
            'trading_enabled': False,
            'database_healthy': False
        }
        
        if not DATABASE_AVAILABLE:
            return overview
            
        try:
            session = get_db_session()
            users = session.query(User).all()
            overview['total_users'] = len(users)
            overview['active_users'] = sum(1 for u in users if u.is_active)
            
            # Get positions
            positions = session.query(Position).filter(Position.is_open == True).all()
            overview['total_positions'] = len(positions)
            overview['unrealized_pnl'] = sum(p.unrealized_pnl or 0 for p in positions)
            
            # Check database health
            overview['database_healthy'] = check_database_health()
            
            session.close()
        except Exception as e:
            logger.error(f"Error getting platform overview: {e}")
            
        # Check if trading is enabled globally
        if CONTROLS_AVAILABLE:
            try:
                controls = get_hard_controls()
                overview['trading_enabled'] = controls.is_trading_enabled()
            except Exception as e:
                logger.error(f"Error checking trading status: {e}")
                
        return overview

    def get_user_summaries(self) -> List[Dict[str, Any]]:
        """Get summary for all users"""
        summaries = []
        
        if not DATABASE_AVAILABLE:
            return summaries
            
        try:
            session = get_db_session()
            users = session.query(User).all()
            
            for user in users:
                summary = {
                    'user_id': user.user_id,
                    'email': user.email or 'N/A',
                    'tier': user.subscription_tier or 'basic',
                    'is_active': user.is_active,
                    'balance': 0.0,
                    'positions': 0,
                    'unrealized_pnl': 0.0,
                    'daily_pnl': 0.0,
                    'can_trade': False,
                    'status': 'unknown'
                }
                
                # Get positions for this user
                positions = session.query(Position).filter(
                    Position.user_id == user.user_id,
                    Position.is_open == True
                ).all()
                summary['positions'] = len(positions)
                summary['unrealized_pnl'] = sum(p.unrealized_pnl or 0 for p in positions)
                
                # Get PnL data if available
                if PNL_TRACKER_AVAILABLE:
                    try:
                        pnl_tracker = get_user_pnl_tracker(user.user_id)
                        summary['daily_pnl'] = pnl_tracker.get_daily_pnl()
                        summary['balance'] = pnl_tracker.get_total_balance()
                    except Exception as e:
                        logger.debug(f"Could not get PnL for {user.user_id}: {e}")
                
                # Get risk status
                if RISK_MANAGER_AVAILABLE:
                    try:
                        risk_mgr = get_user_risk_manager(user.user_id)
                        summary['can_trade'] = risk_mgr.can_trade()
                        summary['status'] = risk_mgr.get_status()
                    except Exception as e:
                        logger.debug(f"Could not get risk status for {user.user_id}: {e}")
                
                summaries.append(summary)
            
            session.close()
        except Exception as e:
            logger.error(f"Error getting user summaries: {e}")
            
        return summaries

    def get_recent_alerts(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get recent system alerts"""
        alerts = []
        
        # Check for alert files or logs
        alert_file = Path("/tmp/nija_alerts.json")
        if alert_file.exists():
            try:
                with open(alert_file, 'r') as f:
                    all_alerts = json.load(f)
                    alerts = all_alerts[-limit:]
            except Exception as e:
                logger.error(f"Error reading alerts: {e}")
        
        return alerts

    def display_overview(self, overview: Dict[str, Any]):
        """Display platform overview"""
        print(f"{Colors.BOLD}📊 PLATFORM OVERVIEW{Colors.ENDC}")
        print("-" * 100)
        
        status_icon = "🟢" if overview['trading_enabled'] else "🔴"
        db_icon = "✅" if overview['database_healthy'] else "⛔"
        
        print(f"  Total Users: {overview['total_users']} | Active: {overview['active_users']} | "
              f"Trading: {status_icon} {'ENABLED' if overview['trading_enabled'] else 'DISABLED'}")
        print(f"  Database: {db_icon} {'Healthy' if overview['database_healthy'] else 'Unhealthy'}")
        print(f"  Total Positions: {overview['total_positions']}")
        
        # PnL color coding
        pnl = overview['unrealized_pnl']
        pnl_color = Colors.OKGREEN if pnl >= 0 else Colors.FAIL
        pnl_sign = "+" if pnl >= 0 else ""
        print(f"  Unrealized P&L: {pnl_color}{pnl_sign}${pnl:,.2f}{Colors.ENDC}")
        print()

    def display_users(self, summaries: List[Dict[str, Any]]):
        """Display user summaries"""
        print(f"{Colors.BOLD}👥 USER STATUS{Colors.ENDC}")
        print("-" * 100)
        
        if not summaries:
            print("  No users found")
            print()
            return
        
        for summary in summaries:
            # Status icons
            active_icon = "✅" if summary['is_active'] else "⛔"
            trade_icon = "🟢" if summary['can_trade'] else "🔴"
            position_icon = "📈" if summary['positions'] > 0 else "  "
            
            # PnL color
            pnl = summary['unrealized_pnl']
            pnl_color = Colors.OKGREEN if pnl >= 0 else Colors.FAIL
            pnl_sign = "+" if pnl >= 0 else ""
            
            print(f"  {active_icon} {trade_icon} {position_icon} {summary['user_id']} ({summary['tier']})")
            print(f"      Balance: ${summary['balance']:,.2f} | Positions: {summary['positions']} | "
                  f"P&L: {pnl_color}{pnl_sign}${pnl:,.2f}{Colors.ENDC}")
            
            if self.detailed:
                print(f"      Email: {summary['email']} | Status: {summary['status']}")
                print(f"      Daily P&L: ${summary['daily_pnl']:,.2f}")
        
        print()

    def display_alerts(self, alerts: List[Dict[str, Any]]):
        """Display recent alerts"""
        print(f"{Colors.BOLD}🚨 RECENT ALERTS{Colors.ENDC}")
        print("-" * 100)
        
        if not alerts:
            print(f"  {Colors.OKGREEN}No recent alerts{Colors.ENDC}")
            print()
            return
        
        for alert in alerts:
            severity = alert.get('severity', 'info').upper()
            color = Colors.FAIL if severity == 'ERROR' else Colors.WARNING if severity == 'WARNING' else Colors.OKBLUE
            timestamp = alert.get('timestamp', 'N/A')
            message = alert.get('message', 'No message')
            
            print(f"  {color}[{severity}]{Colors.ENDC} {timestamp} - {message}")
        
        print()

    def display_menu(self):
        """Display interactive menu"""
        print(f"{Colors.BOLD}⚡ QUICK ACTIONS{Colors.ENDC}")
        print("-" * 100)
        print("  [R] Refresh Now    [E] Emergency Stop    [P] Pause Trading")
        print("  [S] Start Trading  [U] User Status       [Q] Quit")
        print("-" * 100)
        print(f"\nAuto-refresh: {self.refresh_interval}s | Press a key for action or wait for auto-refresh...")

    def execute_action(self, action: str) -> bool:
        """Execute a quick action"""
        action = action.lower()
        
        if action == 'q':
            return False
        elif action == 'r':
            # Just refresh
            pass
        elif action == 'e':
            self.emergency_stop()
        elif action == 'p':
            self.pause_trading()
        elif action == 's':
            self.start_trading()
        elif action == 'u':
            self.show_user_status()
        
        return True

    def emergency_stop(self):
        """Execute emergency stop"""
        print(f"\n{Colors.FAIL}{Colors.BOLD}⚠️  EMERGENCY STOP INITIATED{Colors.ENDC}")
        
        if CONTROLS_AVAILABLE:
            try:
                controls = get_hard_controls()
                controls.disable_trading()
                print(f"{Colors.OKGREEN}✓ Trading disabled globally{Colors.ENDC}")
            except Exception as e:
                print(f"{Colors.FAIL}✗ Error disabling trading: {e}{Colors.ENDC}")
        else:
            print(f"{Colors.WARNING}Controls not available{Colors.ENDC}")
        
        input("\nPress Enter to continue...")

    def pause_trading(self):
        """Pause trading"""
        print(f"\n{Colors.WARNING}⏸️  Pausing trading...{Colors.ENDC}")
        
        if CONTROLS_AVAILABLE:
            try:
                controls = get_hard_controls()
                controls.disable_trading()
                print(f"{Colors.OKGREEN}✓ Trading paused{Colors.ENDC}")
            except Exception as e:
                print(f"{Colors.FAIL}✗ Error: {e}{Colors.ENDC}")
        
        input("\nPress Enter to continue...")

    def start_trading(self):
        """Start/resume trading"""
        print(f"\n{Colors.OKGREEN}▶️  Starting trading...{Colors.ENDC}")
        
        if CONTROLS_AVAILABLE:
            try:
                controls = get_hard_controls()
                controls.enable_trading()
                print(f"{Colors.OKGREEN}✓ Trading enabled{Colors.ENDC}")
            except Exception as e:
                print(f"{Colors.FAIL}✗ Error: {e}{Colors.ENDC}")
        
        input("\nPress Enter to continue...")

    def show_user_status(self):
        """Show detailed user status using existing tool"""
        print(f"\n{Colors.OKCYAN}📊 Running user status summary...{Colors.ENDC}\n")
        
        try:
            subprocess.run([sys.executable, "user_status_summary.py", "--detailed"])
        except Exception as e:
            print(f"{Colors.FAIL}Error running user status: {e}{Colors.ENDC}")
        
        input("\nPress Enter to continue...")

    def run_dashboard(self):
        """Run the main dashboard loop"""
        self.running = True
        
        while self.running:
            try:
                self.clear_screen()
                self.print_header()
                
                # Get and display data
                overview = self.get_platform_overview()
                summaries = self.get_user_summaries()
                alerts = self.get_recent_alerts()
                
                self.display_overview(overview)
                self.display_users(summaries)
                self.display_alerts(alerts)
                self.display_menu()
                
                # Wait for user input or timeout
                import select
                if sys.platform != 'win32':
                    # Unix-like systems
                    readable, _, _ = select.select([sys.stdin], [], [], self.refresh_interval)
                    if readable:
                        action = sys.stdin.readline().strip()
                        if action and not self.execute_action(action):
                            break
                else:
                    # Windows - just sleep and auto-refresh
                    time.sleep(self.refresh_interval)
                    
            except KeyboardInterrupt:
                print(f"\n\n{Colors.WARNING}Interrupted by user{Colors.ENDC}")
                break
            except Exception as e:
                logger.error(f"Error in dashboard loop: {e}")
                print(f"\n{Colors.FAIL}Error: {e}{Colors.ENDC}")
                time.sleep(5)
        
        print(f"\n{Colors.OKGREEN}Control Center closed.{Colors.ENDC}\n")


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description="NIJA Control Center - Interactive CLI Dashboard",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Start control center with default settings
  python nija_control_center.py

  # Custom refresh interval
  python nija_control_center.py --refresh-interval 5

  # Show detailed information
  python nija_control_center.py --detailed

  # One-time snapshot (no loop)
  python nija_control_center.py --snapshot
        """
    )
    
    parser.add_argument('--refresh-interval', type=int, default=10,
                        help='Auto-refresh interval in seconds (default: 10)')
    parser.add_argument('--detailed', action='store_true',
                        help='Show detailed information for each user')
    parser.add_argument('--snapshot', action='store_true',
                        help='Show one-time snapshot and exit')
    
    args = parser.parse_args()
    
    # Initialize database if available
    if DATABASE_AVAILABLE:
        try:
            init_database()
        except Exception as e:
            logger.warning(f"Could not initialize database: {e}")
    
    # Create and run control center
    control_center = NIJAControlCenter(
        refresh_interval=args.refresh_interval,
        detailed=args.detailed
    )
    
    if args.snapshot:
        # Just show once and exit
        control_center.clear_screen()
        control_center.print_header()
        overview = control_center.get_platform_overview()
        summaries = control_center.get_user_summaries()
        alerts = control_center.get_recent_alerts()
        control_center.display_overview(overview)
        control_center.display_users(summaries)
        control_center.display_alerts(alerts)
    else:
        # Run interactive dashboard
        control_center.run_dashboard()


if __name__ == '__main__':
    main()
