"""
NIJA Risk Acknowledgement Module - Mandatory Risk Confirmation Gate

CRITICAL COMPLIANCE MODULE - Users MUST acknowledge risks before live trading.

This module ensures:
    ✅ User explicitly acknowledges risks before LIVE trading
    ✅ Acknowledgement is timestamped and stored locally
    ✅ Re-acknowledgement required after app updates
    ✅ Re-acknowledgement required after 30 days of inactivity
    ✅ No LIVE trading without valid acknowledgement

Apple App Store requirement for financial applications.

Author: NIJA Trading Systems
Version: 1.0
Date: February 2026
"""

import os
import json
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, asdict
from pathlib import Path

logger = logging.getLogger("nija.risk_acknowledgement")


@dataclass
class RiskAcknowledgement:
    """Represents a user's risk acknowledgement"""
    timestamp: str  # ISO format
    app_version: str
    acknowledgements: List[str]  # List of specific risks acknowledged
    user_ip: Optional[str] = None  # Optional for audit trail
    device_id: Optional[str] = None  # Optional for device tracking
    

class RiskAcknowledgementManager:
    """
    Manages user risk acknowledgements for live trading.
    
    CRITICAL: No live trading allowed without valid acknowledgement.
    """
    
    # Required risk acknowledgements
    REQUIRED_ACKNOWLEDGEMENTS = [
        "risk_of_loss",
        "user_responsibility",
        "no_guaranteed_returns",
        "no_financial_advice",
        "monitoring_required",
        "terms_accepted",
    ]
    
    # Full text of each required acknowledgement
    ACKNOWLEDGEMENT_TEXT = {
        "risk_of_loss": (
            "I understand that trading cryptocurrencies and other financial instruments "
            "involves substantial risk of loss, and I may lose all invested capital."
        ),
        "user_responsibility": (
            "I understand that NIJA is a tool for executing MY OWN trading strategy, "
            "and I am solely responsible for all trading decisions."
        ),
        "no_guaranteed_returns": (
            "I understand that past performance does not guarantee future results "
            "and that NIJA makes no promises or guarantees about profitability."
        ),
        "no_financial_advice": (
            "I understand that NIJA does not provide financial advice, investment "
            "recommendations, or guaranteed returns."
        ),
        "monitoring_required": (
            "I understand that I am responsible for monitoring my account, managing risk, "
            "understanding exchange fees and costs, and compliance with applicable laws."
        ),
        "terms_accepted": (
            "I have read and agree to the Terms of Service, Privacy Policy, "
            "and Risk Disclosure."
        ),
    }
    
    # How long acknowledgement is valid (30 days)
    ACKNOWLEDGEMENT_VALIDITY_DAYS = 30
    
    def __init__(self, state_file: Optional[str] = None):
        """
        Initialize risk acknowledgement manager.
        
        Args:
            state_file: Path to state file (default: .nija_risk_acknowledgement.json)
        """
        self._state_file = state_file or os.path.join(
            os.path.dirname(__file__),
            "..",
            ".nija_risk_acknowledgement.json"
        )
        
        self._current_acknowledgement: Optional[RiskAcknowledgement] = None
        self._acknowledgement_history: List[RiskAcknowledgement] = []
        
        # Load existing acknowledgements
        self._load_state()
        
        logger.info(f"🛡️  Risk Acknowledgement Manager initialized")
        
    def _load_state(self):
        """Load persisted acknowledgements"""
        try:
            if os.path.exists(self._state_file):
                with open(self._state_file, 'r') as f:
                    data = json.load(f)
                    
                    # Load current acknowledgement
                    if 'current' in data:
                        self._current_acknowledgement = RiskAcknowledgement(**data['current'])
                        
                    # Load history
                    if 'history' in data:
                        self._acknowledgement_history = [
                            RiskAcknowledgement(**ack) for ack in data['history']
                        ]
                        
                logger.info("📂 Loaded risk acknowledgement state")
        except Exception as e:
            logger.error(f"❌ Error loading risk acknowledgement state: {e}")
            
    def _persist_state(self):
        """Persist acknowledgements to disk"""
        try:
            data = {
                'current': asdict(self._current_acknowledgement) if self._current_acknowledgement else None,
                'history': [asdict(ack) for ack in self._acknowledgement_history],
                'last_updated': datetime.utcnow().isoformat()
            }
            
            # Ensure directory exists
            os.makedirs(os.path.dirname(self._state_file), exist_ok=True)
            
            # Write atomically
            temp_file = f"{self._state_file}.tmp"
            with open(temp_file, 'w') as f:
                json.dump(data, f, indent=2)
            os.replace(temp_file, self._state_file)
            
            logger.debug("💾 Risk acknowledgement state persisted")
        except Exception as e:
            logger.error(f"❌ Error persisting risk acknowledgement state: {e}")
            
    def record_acknowledgement(
        self,
        app_version: str,
        acknowledgements: List[str],
        user_ip: Optional[str] = None,
        device_id: Optional[str] = None
    ) -> bool:
        """
        Record a new risk acknowledgement.
        
        Args:
            app_version: Current app version
            acknowledgements: List of acknowledgement IDs that user accepted
            user_ip: Optional user IP for audit trail
            device_id: Optional device ID for tracking
            
        Returns:
            True if successful
        """
        # Verify all required acknowledgements are present
        missing = set(self.REQUIRED_ACKNOWLEDGEMENTS) - set(acknowledgements)
        if missing:
            logger.error(f"❌ Missing required acknowledgements: {missing}")
            return False
            
        # Create acknowledgement record
        ack = RiskAcknowledgement(
            timestamp=datetime.utcnow().isoformat(),
            app_version=app_version,
            acknowledgements=acknowledgements,
            user_ip=user_ip,
            device_id=device_id
        )
        
        # Store as current
        self._current_acknowledgement = ack
        
        # Add to history
        self._acknowledgement_history.append(ack)
        
        # Persist
        self._persist_state()
        
        logger.info("✅ Risk acknowledgement recorded")
        logger.info(f"   App version: {app_version}")
        logger.info(f"   Timestamp: {ack.timestamp}")
        
        return True
        
    def is_acknowledgement_valid(self, app_version: str) -> bool:
        """
        Check if current acknowledgement is valid for live trading.
        
        Args:
            app_version: Current app version
            
        Returns:
            True if acknowledgement is valid
        """
        if not self._current_acknowledgement:
            logger.warning("⚠️  No risk acknowledgement on file")
            return False
            
        # Check if all required acknowledgements are present
        ack_ids = set(self._current_acknowledgement.acknowledgements)
        required = set(self.REQUIRED_ACKNOWLEDGEMENTS)
        if not required.issubset(ack_ids):
            logger.warning("⚠️  Missing required acknowledgements")
            return False
            
        # Check if acknowledgement is recent enough
        ack_time = datetime.fromisoformat(self._current_acknowledgement.timestamp)
        age = datetime.utcnow() - ack_time
        if age > timedelta(days=self.ACKNOWLEDGEMENT_VALIDITY_DAYS):
            logger.warning(f"⚠️  Risk acknowledgement expired ({age.days} days old)")
            return False
            
        # Check if app version has changed (major/minor version)
        # If version changed significantly, require re-acknowledgement
        ack_version = self._current_acknowledgement.app_version
        if self._version_changed_significantly(ack_version, app_version):
            logger.warning(
                f"⚠️  App version changed significantly: "
                f"{ack_version} -> {app_version}, re-acknowledgement required"
            )
            return False
            
        return True
        
    def _version_changed_significantly(self, old_version: str, new_version: str) -> bool:
        """
        Check if version changed significantly (major or minor version bump).
        
        Args:
            old_version: Previous version (e.g., "1.2.3")
            new_version: Current version (e.g., "1.3.0")
            
        Returns:
            True if significant change (major or minor version)
        """
        try:
            old_parts = old_version.split('.')
            new_parts = new_version.split('.')
            
            # Compare major and minor versions
            if len(old_parts) >= 2 and len(new_parts) >= 2:
                old_major_minor = (old_parts[0], old_parts[1])
                new_major_minor = (new_parts[0], new_parts[1])
                return old_major_minor != new_major_minor
        except Exception:
            # If version parsing fails, be conservative and require re-acknowledgement
            return True
            
        return False
        
    def assert_acknowledgement_valid(self, app_version: str):
        """
        Assert that risk acknowledgement is valid for live trading.
        Raises RuntimeError if not valid.
        
        Args:
            app_version: Current app version
        """
        if not self.is_acknowledgement_valid(app_version):
            raise RuntimeError(
                "Cannot enable live trading: Risk acknowledgement required. "
                "User must review and accept risk disclosure before trading with real capital."
            )
            
    def get_acknowledgement_status(self, app_version: str) -> Dict[str, Any]:
        """
        Get detailed status of current acknowledgement.
        
        Args:
            app_version: Current app version
            
        Returns:
            Status dictionary
        """
        if not self._current_acknowledgement:
            return {
                'has_acknowledgement': False,
                'is_valid': False,
                'reason': 'No acknowledgement on file',
                'action_required': 'User must accept risk disclosure'
            }
            
        ack_time = datetime.fromisoformat(self._current_acknowledgement.timestamp)
        age_days = (datetime.utcnow() - ack_time).days
        
        is_valid = self.is_acknowledgement_valid(app_version)
        
        status = {
            'has_acknowledgement': True,
            'is_valid': is_valid,
            'timestamp': self._current_acknowledgement.timestamp,
            'age_days': age_days,
            'app_version': self._current_acknowledgement.app_version,
            'current_app_version': app_version,
            'total_acknowledgements': len(self._acknowledgement_history),
        }
        
        if not is_valid:
            # Determine why invalid
            if age_days > self.ACKNOWLEDGEMENT_VALIDITY_DAYS:
                status['reason'] = f'Expired ({age_days} days old, max {self.ACKNOWLEDGEMENT_VALIDITY_DAYS})'
                status['action_required'] = 'Re-accept risk disclosure'
            elif self._version_changed_significantly(
                self._current_acknowledgement.app_version,
                app_version
            ):
                status['reason'] = 'App version changed'
                status['action_required'] = 'Re-accept risk disclosure for new version'
            else:
                status['reason'] = 'Missing required acknowledgements'
                status['action_required'] = 'Complete risk disclosure'
                
        return status
        
    def get_required_acknowledgements_text(self) -> Dict[str, str]:
        """Get full text of all required acknowledgements"""
        return self.ACKNOWLEDGEMENT_TEXT.copy()
        
    def get_acknowledgement_history(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get recent acknowledgement history"""
        history = self._acknowledgement_history[-limit:] if self._acknowledgement_history else []
        return [asdict(ack) for ack in history]


# Global singleton instance
_risk_acknowledgement_manager: Optional[RiskAcknowledgementManager] = None


def get_risk_acknowledgement_manager() -> RiskAcknowledgementManager:
    """Get the global risk acknowledgement manager instance (singleton)"""
    global _risk_acknowledgement_manager
    
    if _risk_acknowledgement_manager is None:
        _risk_acknowledgement_manager = RiskAcknowledgementManager()
        
    return _risk_acknowledgement_manager


def require_risk_acknowledgement(app_version: str):
    """
    Decorator/function to require risk acknowledgement.
    
    Usage:
        require_risk_acknowledgement("1.0.0")
        enable_live_trading()
    """
    manager = get_risk_acknowledgement_manager()
    manager.assert_acknowledgement_valid(app_version)


# Example usage and testing
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    print("\n=== Risk Acknowledgement Manager Test ===\n")
    
    manager = get_risk_acknowledgement_manager()
    app_version = "1.0.0"
    
    # Check initial status
    status = manager.get_acknowledgement_status(app_version)
    print(f"Initial status: {status}\n")
    
    # Show required acknowledgements
    print("Required acknowledgements:")
    for ack_id, text in manager.get_required_acknowledgements_text().items():
        print(f"\n{ack_id}:")
        print(f"  {text}")
        
    # Record acknowledgement
    print("\n\n--- Recording acknowledgement ---")
    success = manager.record_acknowledgement(
        app_version=app_version,
        acknowledgements=manager.REQUIRED_ACKNOWLEDGEMENTS,
        device_id="test_device_123"
    )
    print(f"Record success: {success}")
    
    # Check status after acknowledgement
    print("\n--- Status after acknowledgement ---")
    status = manager.get_acknowledgement_status(app_version)
    for key, value in status.items():
        print(f"  {key}: {value}")
        
    # Test assertion
    print("\n--- Testing assertion ---")
    try:
        manager.assert_acknowledgement_valid(app_version)
        print("✅ Assertion passed - live trading allowed")
    except RuntimeError as e:
        print(f"❌ Assertion failed: {e}")
