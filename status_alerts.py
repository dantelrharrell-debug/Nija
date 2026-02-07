#!/usr/bin/env python3
"""
NIJA Live Status Alerting System
=================================

Monitors user status and sends alerts for:
- High risk users (daily loss > 5%)
- Circuit breaker triggers
- Missing API credentials
- Failed readiness checks
- Low balance warnings

Supports multiple notification channels:
- Slack webhook
- Email
- Console output
- Log file

Usage:
    python status_alerts.py
    python status_alerts.py --check-only  # Check without sending alerts
    python status_alerts.py --slack-webhook URL
"""

import os
import sys
import json
import logging
import argparse
import subprocess
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@dataclass
class Alert:
    """Alert message"""
    level: str  # critical, warning, info
    user_id: str
    message: str
    details: Dict = None


class StatusAlerter:
    """Monitor user status and send alerts"""
    
    # Alert thresholds
    HIGH_RISK_THRESHOLD = 5.0  # Daily loss % for high risk
    MEDIUM_RISK_THRESHOLD = 2.0  # Daily loss % for medium risk
    LOW_BALANCE_THRESHOLD = 100.0  # Minimum balance in USD
    
    def __init__(self, slack_webhook: Optional[str] = None, email_to: Optional[str] = None):
        """Initialize alerter"""
        self.slack_webhook = slack_webhook or os.getenv('SLACK_WEBHOOK_URL')
        self.email_to = email_to or os.getenv('ALERT_EMAIL')
        self.alerts: List[Alert] = []
    
    def check_status(self) -> List[Alert]:
        """
        Check user status and generate alerts
        
        Returns:
            List of Alert objects
        """
        self.alerts = []
        
        try:
            # Run status summary to get current state
            result = subprocess.run(
                ['python', 'user_status_summary.py', '--json', '--quiet'],
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if result.returncode != 0:
                logger.error(f"Failed to get status: {result.stderr}")
                return self.alerts
            
            status = json.loads(result.stdout)
            
            # Check each user
            for user in status.get('users', []):
                self._check_user(user)
            
            # Check platform-wide issues
            self._check_platform(status['platform_overview'])
            
        except Exception as e:
            logger.error(f"Error checking status: {e}")
        
        return self.alerts
    
    def _check_user(self, user: Dict):
        """Check individual user for issues"""
        user_id = user['user_id']
        
        # Check 1: High risk level
        if user['risk_level'] == 'high':
            daily_pnl = user.get('daily_pnl', 0)
            balance = user.get('total_balance_usd', 0)
            loss_pct = (abs(daily_pnl) / balance * 100) if balance > 0 else 0
            
            self.alerts.append(Alert(
                level='critical',
                user_id=user_id,
                message=f"🔴 High risk: Daily loss {loss_pct:.1f}%",
                details={'daily_pnl': daily_pnl, 'balance': balance}
            ))
        
        # Check 2: Circuit breaker triggered
        if user.get('circuit_breaker', False):
            self.alerts.append(Alert(
                level='warning',
                user_id=user_id,
                message=f"🚨 Circuit breaker triggered",
                details={'daily_pnl': user.get('daily_pnl', 0)}
            ))
        
        # Check 3: Trading disabled
        if not user.get('can_trade', True):
            reason = user.get('trading_status', 'Unknown reason')
            
            # Check if it's due to missing credentials
            if 'credential' in reason.lower() or 'api' in reason.lower():
                self.alerts.append(Alert(
                    level='critical',
                    user_id=user_id,
                    message=f"🔑 Missing API credentials",
                    details={'reason': reason}
                ))
            # Check if it's LIVE_CAPITAL_VERIFIED
            elif 'LIVE_CAPITAL_VERIFIED' in reason:
                self.alerts.append(Alert(
                    level='info',
                    user_id=user_id,
                    message=f"ℹ️  Live trading not enabled (safety mode)",
                    details={'reason': reason}
                ))
            else:
                self.alerts.append(Alert(
                    level='warning',
                    user_id=user_id,
                    message=f"⛔ Trading disabled: {reason}",
                    details={'reason': reason}
                ))
        
        # Check 4: Low balance
        balance = user.get('total_balance_usd', 0)
        if balance > 0 and balance < self.LOW_BALANCE_THRESHOLD:
            self.alerts.append(Alert(
                level='warning',
                user_id=user_id,
                message=f"💰 Low balance: ${balance:.2f}",
                details={'balance': balance}
            ))
        
        # Check 5: No configured brokers
        if not user.get('configured_brokers', []):
            self.alerts.append(Alert(
                level='warning',
                user_id=user_id,
                message=f"⚠️  No brokers configured",
                details={}
            ))
    
    def _check_platform(self, overview: Dict):
        """Check platform-wide metrics"""
        total_users = overview.get('total_users', 0)
        trading_ready = overview.get('trading_ready', 0)
        
        # Alert if less than 50% of users can trade
        if total_users > 0:
            ready_pct = (trading_ready / total_users) * 100
            if ready_pct < 50:
                self.alerts.append(Alert(
                    level='warning',
                    user_id='PLATFORM',
                    message=f"📊 Only {ready_pct:.0f}% of users trading-ready ({trading_ready}/{total_users})",
                    details={'total_users': total_users, 'trading_ready': trading_ready}
                ))
    
    def send_alerts(self, dry_run: bool = False) -> bool:
        """
        Send all collected alerts
        
        Args:
            dry_run: If True, only print alerts without sending
            
        Returns:
            True if alerts were sent successfully
        """
        if not self.alerts:
            logger.info("✅ No alerts to send - all systems healthy")
            return True
        
        # Group alerts by level
        critical = [a for a in self.alerts if a.level == 'critical']
        warnings = [a for a in self.alerts if a.level == 'warning']
        info = [a for a in self.alerts if a.level == 'info']
        
        # Print summary
        print("\n" + "=" * 80)
        print("🚨 NIJA STATUS ALERTS")
        print(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * 80)
        
        if critical:
            print(f"\n🔴 CRITICAL ({len(critical)}):")
            for alert in critical:
                print(f"   • {alert.user_id}: {alert.message}")
        
        if warnings:
            print(f"\n🟡 WARNINGS ({len(warnings)}):")
            for alert in warnings:
                print(f"   • {alert.user_id}: {alert.message}")
        
        if info:
            print(f"\nℹ️  INFO ({len(info)}):")
            for alert in info:
                print(f"   • {alert.user_id}: {alert.message}")
        
        print("\n" + "=" * 80)
        
        if dry_run:
            print("\n(Dry run - no alerts sent)")
            return True
        
        # Send to configured channels
        success = True
        
        if self.slack_webhook:
            success &= self._send_slack()
        
        if self.email_to:
            success &= self._send_email()
        
        # Always log to file
        self._log_to_file()
        
        return success
    
    def _send_slack(self) -> bool:
        """Send alerts to Slack"""
        try:
            import requests
            
            # Group alerts by level
            critical = [a for a in self.alerts if a.level == 'critical']
            warnings = [a for a in self.alerts if a.level == 'warning']
            
            # Build message
            blocks = [
                {
                    "type": "header",
                    "text": {
                        "type": "plain_text",
                        "text": "🚨 NIJA Status Alerts"
                    }
                }
            ]
            
            if critical:
                blocks.append({
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*🔴 Critical Issues ({len(critical)}):*"
                    }
                })
                for alert in critical[:5]:  # Limit to 5
                    blocks.append({
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"• `{alert.user_id}`: {alert.message}"
                        }
                    })
            
            if warnings:
                blocks.append({
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*🟡 Warnings ({len(warnings)}):*"
                    }
                })
                for alert in warnings[:5]:  # Limit to 5
                    blocks.append({
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"• `{alert.user_id}`: {alert.message}"
                        }
                    })
            
            # Send to Slack
            response = requests.post(
                self.slack_webhook,
                json={"blocks": blocks},
                timeout=10
            )
            
            if response.status_code == 200:
                logger.info("✅ Slack notification sent")
                return True
            else:
                logger.error(f"Failed to send Slack notification: {response.status_code}")
                return False
                
        except Exception as e:
            logger.error(f"Error sending Slack notification: {e}")
            return False
    
    def _send_email(self) -> bool:
        """Send alerts via email"""
        try:
            # Build email body
            body = f"""NIJA Status Alerts
Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

"""
            critical = [a for a in self.alerts if a.level == 'critical']
            warnings = [a for a in self.alerts if a.level == 'warning']
            
            if critical:
                body += f"\nCRITICAL ALERTS ({len(critical)}):\n"
                for alert in critical:
                    body += f"  • {alert.user_id}: {alert.message}\n"
            
            if warnings:
                body += f"\nWARNINGS ({len(warnings)}):\n"
                for alert in warnings:
                    body += f"  • {alert.user_id}: {alert.message}\n"
            
            # Send email using system mail command
            import subprocess
            result = subprocess.run(
                ['mail', '-s', 'NIJA Status Alerts', self.email_to],
                input=body.encode(),
                timeout=10
            )
            
            if result.returncode == 0:
                logger.info("✅ Email notification sent")
                return True
            else:
                logger.error("Failed to send email notification")
                return False
                
        except Exception as e:
            logger.error(f"Error sending email: {e}")
            return False
    
    def _log_to_file(self):
        """Log alerts to file"""
        try:
            log_dir = 'logs/alerts'
            os.makedirs(log_dir, exist_ok=True)
            
            log_file = f"{log_dir}/alerts_{datetime.now().strftime('%Y%m%d')}.log"
            
            with open(log_file, 'a') as f:
                f.write(f"\n{'=' * 80}\n")
                f.write(f"Alerts at {datetime.now().isoformat()}\n")
                f.write(f"{'=' * 80}\n")
                
                for alert in self.alerts:
                    f.write(f"[{alert.level.upper()}] {alert.user_id}: {alert.message}\n")
                    if alert.details:
                        f.write(f"  Details: {json.dumps(alert.details)}\n")
            
            logger.info(f"✅ Alerts logged to {log_file}")
            
        except Exception as e:
            logger.error(f"Error logging to file: {e}")


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description='NIJA Live Status Alerting - Monitor and alert on user status issues'
    )
    parser.add_argument(
        '--check-only',
        action='store_true',
        help='Check status and display alerts without sending notifications'
    )
    parser.add_argument(
        '--slack-webhook',
        type=str,
        help='Slack webhook URL for notifications'
    )
    parser.add_argument(
        '--email',
        type=str,
        help='Email address for alert notifications'
    )
    
    args = parser.parse_args()
    
    # Create alerter
    alerter = StatusAlerter(
        slack_webhook=args.slack_webhook,
        email_to=args.email
    )
    
    # Check status
    print("🔍 Checking user status...")
    alerts = alerter.check_status()
    
    # Send alerts
    alerter.send_alerts(dry_run=args.check_only)


if __name__ == "__main__":
    main()
