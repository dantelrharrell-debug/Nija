#!/usr/bin/env python3
"""
NIJA Status Monitor Daemon
===========================

Runs continuous monitoring of user status with:
- Periodic status checks (configurable interval)
- Automatic snapshot persistence
- Alert generation for issues
- Health metrics tracking

Designed to run as a supervised daemon process.

Usage:
    python status_monitor.py
    python status_monitor.py --interval 300  # Check every 5 minutes
"""

import os
import sys
import time
import json
import signal
import logging
import argparse
import subprocess
from datetime import datetime
from pathlib import Path

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class StatusMonitor:
    """Continuous status monitoring daemon"""
    
    def __init__(self, check_interval: int = 300, snapshot_dir: str = 'snapshots'):
        """
        Initialize monitor
        
        Args:
            check_interval: Seconds between status checks (default 5 minutes)
            snapshot_dir: Directory to save snapshots
        """
        self.check_interval = check_interval
        self.snapshot_dir = Path(snapshot_dir)
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)
        self.running = False
        self.last_status = None
        
        # Setup signal handlers for graceful shutdown
        signal.signal(signal.SIGTERM, self._signal_handler)
        signal.signal(signal.SIGINT, self._signal_handler)
    
    def _signal_handler(self, signum, frame):
        """Handle shutdown signals"""
        logger.info(f"Received signal {signum}, shutting down gracefully...")
        self.running = False
    
    def start(self):
        """Start monitoring loop"""
        logger.info("=" * 80)
        logger.info("🚀 NIJA Status Monitor Started")
        logger.info(f"   Check interval: {self.check_interval} seconds")
        logger.info(f"   Snapshot directory: {self.snapshot_dir}")
        logger.info("=" * 80)
        
        self.running = True
        iteration = 0
        
        while self.running:
            iteration += 1
            try:
                logger.info(f"\n{'=' * 60}")
                logger.info(f"Status Check #{iteration} at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
                logger.info(f"{'=' * 60}")
                
                # Perform status check
                self._check_status()
                
                # Check for alerts
                self._check_alerts()
                
                # Save snapshot
                self._save_snapshot()
                
                # Wait for next check
                if self.running:
                    logger.info(f"✅ Check complete. Next check in {self.check_interval} seconds...")
                    time.sleep(self.check_interval)
                    
            except Exception as e:
                logger.error(f"Error during monitoring iteration: {e}", exc_info=True)
                # Continue running even if one iteration fails
                time.sleep(60)  # Wait 1 minute before retry
        
        logger.info("🛑 Status Monitor stopped")
    
    def _check_status(self):
        """Run status check and save results"""
        try:
            result = subprocess.run(
                ['python', 'user_status_summary.py', '--json', '--quiet'],
                capture_output=True,
                text=True,
                timeout=60
            )
            
            if result.returncode != 0:
                logger.error(f"Status check failed: {result.stderr}")
                return
            
            self.last_status = json.loads(result.stdout)
            
            # Log summary
            overview = self.last_status.get('platform_overview', {})
            logger.info(f"📊 Platform Status:")
            logger.info(f"   Total Users: {overview.get('total_users', 0)}")
            logger.info(f"   Trading Ready: {overview.get('trading_ready', 0)}")
            logger.info(f"   Total Capital: ${overview.get('total_capital_usd', 0):,.2f}")
            logger.info(f"   Unrealized P&L: ${overview.get('total_unrealized_pnl', 0):,.2f}")
            
            # Count issues
            users = self.last_status.get('users', [])
            high_risk = sum(1 for u in users if u.get('risk_level') == 'high')
            circuit_breakers = sum(1 for u in users if u.get('circuit_breaker', False))
            disabled = sum(1 for u in users if not u.get('can_trade', True))
            
            if high_risk > 0:
                logger.warning(f"   ⚠️  High risk users: {high_risk}")
            if circuit_breakers > 0:
                logger.warning(f"   🚨 Circuit breakers: {circuit_breakers}")
            if disabled > 0:
                logger.info(f"   ⛔ Trading disabled: {disabled}")
                
        except subprocess.TimeoutExpired:
            logger.error("Status check timed out")
        except Exception as e:
            logger.error(f"Error checking status: {e}")
    
    def _check_alerts(self):
        """Check for alert conditions"""
        try:
            result = subprocess.run(
                ['python', 'status_alerts.py', '--check-only'],
                capture_output=True,
                text=True,
                timeout=60
            )
            
            if result.returncode != 0:
                logger.error(f"Alert check failed: {result.stderr}")
            else:
                # Parse output for alert counts
                output = result.stdout
                if 'CRITICAL' in output:
                    logger.warning("🔴 Critical alerts detected!")
                if 'No alerts' in output:
                    logger.info("✅ No alerts - all systems healthy")
                    
        except subprocess.TimeoutExpired:
            logger.error("Alert check timed out")
        except Exception as e:
            logger.error(f"Error checking alerts: {e}")
    
    def _save_snapshot(self):
        """Save current status snapshot"""
        if not self.last_status:
            logger.warning("No status data to snapshot")
            return
        
        try:
            # Save daily snapshot
            date_str = datetime.now().strftime('%Y%m%d')
            daily_file = self.snapshot_dir / f"daily_{date_str}.json"
            
            # Also save timestamped snapshot
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            timestamped_file = self.snapshot_dir / f"status_{timestamp}.json"
            
            # Save both
            for filepath in [daily_file, timestamped_file]:
                with open(filepath, 'w') as f:
                    json.dump(self.last_status, f, indent=2)
            
            logger.info(f"💾 Snapshot saved: {timestamped_file.name}")
            
            # Cleanup old snapshots (keep last 30 days)
            self._cleanup_old_snapshots(days=30)
            
        except Exception as e:
            logger.error(f"Error saving snapshot: {e}")
    
    def _cleanup_old_snapshots(self, days: int = 30):
        """Remove snapshots older than specified days"""
        try:
            import time
            cutoff_time = time.time() - (days * 86400)
            
            deleted = 0
            for filepath in self.snapshot_dir.glob('status_*.json'):
                if filepath.stat().st_mtime < cutoff_time:
                    filepath.unlink()
                    deleted += 1
            
            if deleted > 0:
                logger.info(f"🗑️  Cleaned up {deleted} old snapshots")
                
        except Exception as e:
            logger.error(f"Error cleaning up snapshots: {e}")


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description='NIJA Status Monitor Daemon - Continuous user status monitoring'
    )
    parser.add_argument(
        '--interval',
        type=int,
        default=300,
        help='Check interval in seconds (default: 300 = 5 minutes)'
    )
    parser.add_argument(
        '--snapshot-dir',
        type=str,
        default='snapshots',
        help='Directory to save status snapshots'
    )
    
    args = parser.parse_args()
    
    # Create and start monitor
    monitor = StatusMonitor(
        check_interval=args.interval,
        snapshot_dir=args.snapshot_dir
    )
    
    monitor.start()


if __name__ == "__main__":
    main()
