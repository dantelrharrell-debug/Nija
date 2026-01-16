"""
Credential Health Monitoring System
====================================

Monitors credential state changes and warns when credentials are lost or invalid.
This helps diagnose recurring disconnection issues by tracking when and how
credentials disappear from the environment.

Features:
- Periodic credential health checks
- Detection of credential loss between checks
- Logging of credential state changes
- Alerts for suspicious credential behavior
- Persistence validation

Usage:
    from credential_health_monitor import CredentialHealthMonitor
    
    monitor = CredentialHealthMonitor()
    monitor.start_monitoring()  # Starts background monitoring
    
    # Or manual check
    status = monitor.check_credential_health()
"""

import os
import time
import logging
import threading
from typing import Dict, Set, Tuple, Optional
from datetime import datetime
from enum import Enum

logger = logging.getLogger('nija.credential_monitor')


class CredentialStatus(Enum):
    """Status of a credential."""
    VALID = "valid"           # Set and non-empty
    MISSING = "missing"       # Not set
    INVALID = "invalid"       # Set but empty/whitespace
    CHANGED = "changed"       # Value changed since last check


class CredentialHealthMonitor:
    """
    Monitors credential health and detects credential loss.
    
    This helps diagnose recurring disconnection issues by:
    1. Tracking which credentials are set
    2. Detecting when credentials disappear
    3. Alerting on suspicious changes
    4. Logging credential state history
    """
    
    def __init__(self, check_interval: int = 300):
        """
        Initialize credential health monitor.
        
        Args:
            check_interval: Seconds between health checks (default: 300 = 5 minutes)
        """
        self.check_interval = check_interval
        self._monitoring_thread: Optional[threading.Thread] = None
        self._stop_monitoring = threading.Event()
        self._last_check_time: Optional[datetime] = None
        
        # Track credential state history
        # Format: {credential_name: (status, value_hash, last_seen)}
        self._credential_state: Dict[str, Tuple[CredentialStatus, str, datetime]] = {}
        
        # Track detected issues
        self._issues_detected: Dict[str, datetime] = {}
        
        # Define required credentials
        self._required_credentials = self._get_required_credentials()
        
    def _get_required_credentials(self) -> Dict[str, Set[str]]:
        """
        Get list of credentials to monitor.
        
        Returns:
            dict: {category: {credential_names}}
        """
        creds = {
            'master_coinbase': {
                'COINBASE_API_KEY',
                'COINBASE_API_SECRET'
            },
            'master_kraken': {
                'KRAKEN_MASTER_API_KEY',
                'KRAKEN_MASTER_API_SECRET'
            },
            'master_alpaca': {
                'ALPACA_API_KEY',
                'ALPACA_API_SECRET'
            }
        }
        
        # Dynamically add user credentials if config is available
        try:
            from config.user_loader import get_user_config_loader
            user_loader = get_user_config_loader()
            enabled_users = user_loader.get_all_enabled_users()
            
            for user in enabled_users:
                user_id = user.user_id
                broker_type = user.broker_type.upper()
                first_name = user_id.split('_')[0].upper()
                
                category = f'user_{user_id}_{broker_type.lower()}'
                
                if broker_type == 'KRAKEN':
                    creds[category] = {
                        f'KRAKEN_USER_{first_name}_API_KEY',
                        f'KRAKEN_USER_{first_name}_API_SECRET'
                    }
                elif broker_type == 'ALPACA':
                    creds[category] = {
                        f'ALPACA_USER_{first_name}_API_KEY',
                        f'ALPACA_USER_{first_name}_API_SECRET'
                    }
        except Exception as e:
            logger.debug(f"Could not load user credentials for monitoring: {e}")
        
        return creds
    
    def _hash_value(self, value: str) -> str:
        """
        Create a hash of the credential value for comparison.
        
        We don't store actual values for security, just a hash to detect changes.
        """
        import hashlib
        return hashlib.sha256(value.encode()).hexdigest()[:16]
    
    def _check_credential(self, name: str) -> Tuple[CredentialStatus, Optional[str]]:
        """
        Check status of a single credential.
        
        Returns:
            (status, value_hash or None)
        """
        value = os.getenv(name, "")
        
        if not value:
            return CredentialStatus.MISSING, None
        
        if not value.strip():
            return CredentialStatus.INVALID, None
        
        # Credential is valid
        return CredentialStatus.VALID, self._hash_value(value)
    
    def check_credential_health(self) -> Dict[str, any]:
        """
        Perform a health check on all credentials.
        
        Returns:
            dict: Health check results
        """
        now = datetime.now()
        results = {
            'timestamp': now.isoformat(),
            'status': 'healthy',
            'issues': [],
            'credentials': {}
        }
        
        for category, cred_names in self._required_credentials.items():
            category_status = {
                'configured': 0,
                'total': len(cred_names),
                'issues': []
            }
            
            for cred_name in cred_names:
                status, value_hash = self._check_credential(cred_name)
                
                # Check if this credential was previously tracked
                if cred_name in self._credential_state:
                    prev_status, prev_hash, prev_time = self._credential_state[cred_name]
                    
                    # Detect credential loss
                    if prev_status == CredentialStatus.VALID and status != CredentialStatus.VALID:
                        issue = f"⚠️  CREDENTIAL LOST: {cred_name} was valid, now {status.value}"
                        logger.error(issue)
                        logger.error(f"   Last seen valid: {prev_time.isoformat()}")
                        logger.error(f"   Time elapsed: {(now - prev_time).total_seconds():.1f} seconds")
                        results['issues'].append(issue)
                        results['status'] = 'unhealthy'
                        self._issues_detected[cred_name] = now
                    
                    # Detect credential change (value changed)
                    elif (status == CredentialStatus.VALID and 
                          prev_status == CredentialStatus.VALID and 
                          value_hash != prev_hash):
                        issue = f"ℹ️  CREDENTIAL CHANGED: {cred_name} value changed"
                        logger.info(issue)
                        logger.info(f"   Previous check: {prev_time.isoformat()}")
                        results['issues'].append(issue)
                    
                    # Detect credential recovery
                    elif prev_status != CredentialStatus.VALID and status == CredentialStatus.VALID:
                        issue = f"✅ CREDENTIAL RECOVERED: {cred_name} is now valid"
                        logger.info(issue)
                        logger.info(f"   Was {prev_status.value} at: {prev_time.isoformat()}")
                        results['issues'].append(issue)
                        # Clear issue if it exists
                        if cred_name in self._issues_detected:
                            del self._issues_detected[cred_name]
                
                # Update state tracking
                self._credential_state[cred_name] = (status, value_hash, now)
                
                # Count configured credentials
                if status == CredentialStatus.VALID:
                    category_status['configured'] += 1
                elif status == CredentialStatus.MISSING:
                    category_status['issues'].append(f"{cred_name}: not set")
                elif status == CredentialStatus.INVALID:
                    category_status['issues'].append(f"{cred_name}: invalid (empty/whitespace)")
            
            results['credentials'][category] = category_status
        
        # Overall health assessment
        total_configured = sum(c['configured'] for c in results['credentials'].values())
        total_required = sum(c['total'] for c in results['credentials'].values())
        
        logger.debug(f"Credential health check: {total_configured}/{total_required} configured")
        
        # Log any ongoing issues
        if self._issues_detected:
            logger.warning(f"⚠️  {len(self._issues_detected)} credential issue(s) detected:")
            for cred, detected_at in self._issues_detected.items():
                duration = (now - detected_at).total_seconds()
                logger.warning(f"   - {cred}: issue for {duration:.0f} seconds")
        
        self._last_check_time = now
        return results
    
    def _monitoring_loop(self):
        """Background monitoring loop."""
        logger.info("🔍 Credential health monitoring started")
        logger.info(f"   Check interval: {self.check_interval} seconds")
        
        while not self._stop_monitoring.is_set():
            try:
                results = self.check_credential_health()
                
                # Log summary
                if results['status'] != 'healthy':
                    logger.warning(f"⚠️  Credential health check: {results['status']}")
                    for issue in results['issues']:
                        logger.warning(f"   {issue}")
                
            except Exception as e:
                logger.error(f"Error in credential health check: {e}")
                import traceback
                logger.debug(traceback.format_exc())
            
            # Wait for next check or stop signal
            self._stop_monitoring.wait(self.check_interval)
        
        logger.info("🔍 Credential health monitoring stopped")
    
    def start_monitoring(self):
        """Start background credential monitoring."""
        if self._monitoring_thread and self._monitoring_thread.is_alive():
            logger.warning("Credential monitoring already running")
            return
        
        self._stop_monitoring.clear()
        self._monitoring_thread = threading.Thread(
            target=self._monitoring_loop,
            name="CredentialHealthMonitor",
            daemon=True
        )
        self._monitoring_thread.start()
        
        logger.info("✅ Credential health monitoring enabled")
    
    def stop_monitoring(self):
        """Stop background monitoring."""
        if not self._monitoring_thread or not self._monitoring_thread.is_alive():
            return
        
        self._stop_monitoring.set()
        self._monitoring_thread.join(timeout=5)
        logger.info("Credential health monitoring stopped")
    
    def get_status_summary(self) -> str:
        """
        Get a human-readable status summary.
        
        Returns:
            str: Formatted status summary
        """
        results = self.check_credential_health()
        
        lines = []
        lines.append("=" * 70)
        lines.append("🔍 CREDENTIAL HEALTH STATUS")
        lines.append("=" * 70)
        lines.append(f"Last Check: {results['timestamp']}")
        lines.append(f"Overall Status: {results['status'].upper()}")
        lines.append("")
        
        for category, status in results['credentials'].items():
            configured = status['configured']
            total = status['total']
            pct = (configured / total * 100) if total > 0 else 0
            
            status_icon = "✅" if configured == total else "⚠️" if configured > 0 else "❌"
            lines.append(f"{status_icon} {category}: {configured}/{total} configured ({pct:.0f}%)")
            
            if status['issues']:
                for issue in status['issues']:
                    lines.append(f"   - {issue}")
        
        if results['issues']:
            lines.append("")
            lines.append("⚠️  ISSUES DETECTED:")
            for issue in results['issues']:
                lines.append(f"   {issue}")
        
        lines.append("=" * 70)
        
        return "\n".join(lines)


# Global singleton instance
_credential_monitor: Optional[CredentialHealthMonitor] = None


def get_credential_monitor() -> CredentialHealthMonitor:
    """Get the global credential monitor instance."""
    global _credential_monitor
    if _credential_monitor is None:
        _credential_monitor = CredentialHealthMonitor()
    return _credential_monitor


def start_credential_monitoring(check_interval: int = 300):
    """
    Start credential health monitoring.
    
    Args:
        check_interval: Seconds between checks (default: 300 = 5 minutes)
    """
    monitor = get_credential_monitor()
    monitor.check_interval = check_interval
    monitor.start_monitoring()
    return monitor


if __name__ == "__main__":
    # CLI usage
    import sys
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s | %(levelname)s | %(message)s'
    )
    
    monitor = CredentialHealthMonitor()
    print(monitor.get_status_summary())
    
    # Optionally start monitoring
    if '--monitor' in sys.argv:
        print("\n🔍 Starting continuous monitoring (Ctrl+C to stop)...")
        monitor.start_monitoring()
        try:
            while True:
                time.sleep(60)
        except KeyboardInterrupt:
            print("\n\nStopping monitoring...")
            monitor.stop_monitoring()
