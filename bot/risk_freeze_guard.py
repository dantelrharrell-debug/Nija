"""
Risk Freeze Guard

Enforces RISK FREEZE policy at runtime. Prevents unauthorized changes to
risk parameters and validates that all changes go through proper approval.

This is a critical safety component that ensures long-term profitability
by preventing ad-hoc risk parameter tweaks.

Author: NIJA Trading Systems
Date: February 12, 2026
"""

import logging
import json
import hashlib
from typing import Dict, Any, Optional, List
from datetime import datetime
from pathlib import Path

logger = logging.getLogger("nija.risk_freeze_guard")


class RiskFreezeViolation(Exception):
    """Raised when RISK FREEZE policy is violated"""
    pass


class EmergencyOverride:
    """Represents an emergency override of RISK FREEZE"""
    
    def __init__(
        self,
        reason: str,
        authorized_by: str,
        parameters_changed: List[str],
        timestamp: Optional[str] = None
    ):
        self.reason = reason
        self.authorized_by = authorized_by
        self.parameters_changed = parameters_changed
        self.timestamp = timestamp or datetime.utcnow().isoformat()
    
    def to_dict(self) -> Dict:
        return {
            'reason': self.reason,
            'authorized_by': self.authorized_by,
            'parameters_changed': self.parameters_changed,
            'timestamp': self.timestamp
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'EmergencyOverride':
        return cls(
            reason=data['reason'],
            authorized_by=data['authorized_by'],
            parameters_changed=data['parameters_changed'],
            timestamp=data.get('timestamp')
        )


class RiskFreezeGuard:
    """
    Enforces RISK FREEZE policy
    
    - Validates risk parameters haven't changed without approval
    - Tracks emergency overrides
    - Alerts on unauthorized changes
    - Maintains audit trail
    """
    
    # Critical risk parameters that are protected
    PROTECTED_PARAMETERS = {
        'max_position_size',
        'min_position_size',
        'max_risk_per_trade',
        'max_daily_loss',
        'max_total_exposure',
        'max_drawdown',
        'max_positions',
        'max_trades_per_day',
        'max_leverage',
        'stop_loss_atr_multiplier',
        'trailing_stop_pct',
        'take_profit_tp1_pct',
        'take_profit_tp2_pct',
        'take_profit_tp3_pct',
        'position_size_base_pct',
        'position_size_max_pct',
        'adx_strong_threshold',
        'volume_threshold',
        'min_signal_score',
    }
    
    def __init__(
        self,
        baseline_config_path: str = "config/risk_versions/baseline_risk_config.json",
        emergency_log_path: str = "logs/risk_freeze_emergency_log.json"
    ):
        """
        Initialize Risk Freeze Guard
        
        Args:
            baseline_config_path: Path to baseline risk configuration
            emergency_log_path: Path to emergency override log
        """
        self.baseline_config_path = Path(baseline_config_path)
        self.emergency_log_path = Path(emergency_log_path)
        
        # Create directories if they don't exist
        self.baseline_config_path.parent.mkdir(parents=True, exist_ok=True)
        self.emergency_log_path.parent.mkdir(parents=True, exist_ok=True)
        
        self.baseline_config: Optional[Dict[str, Any]] = None
        self.baseline_hash: Optional[str] = None
        self.emergency_overrides: List[EmergencyOverride] = []
        
        self._load_baseline()
        self._load_emergency_log()
        
        logger.info("🔒 Risk Freeze Guard initialized")
    
    def _load_baseline(self):
        """Load baseline risk configuration"""
        if self.baseline_config_path.exists():
            try:
                with open(self.baseline_config_path, 'r') as f:
                    self.baseline_config = json.load(f)
                self.baseline_hash = self._compute_hash(self.baseline_config)
                logger.info(f"✅ Loaded baseline risk config (hash: {self.baseline_hash[:8]})")
            except Exception as e:
                logger.error(f"Failed to load baseline risk config: {e}")
        else:
            logger.warning("⚠️  No baseline risk config found - will be created on first save")
    
    def _load_emergency_log(self):
        """Load emergency override log"""
        if self.emergency_log_path.exists():
            try:
                with open(self.emergency_log_path, 'r') as f:
                    data = json.load(f)
                    self.emergency_overrides = [
                        EmergencyOverride.from_dict(override)
                        for override in data
                    ]
                logger.info(f"Loaded {len(self.emergency_overrides)} emergency overrides")
            except Exception as e:
                logger.error(f"Failed to load emergency log: {e}")
    
    def _save_emergency_log(self):
        """Save emergency override log"""
        try:
            with open(self.emergency_log_path, 'w') as f:
                json.dump(
                    [override.to_dict() for override in self.emergency_overrides],
                    f,
                    indent=2
                )
        except Exception as e:
            logger.error(f"Failed to save emergency log: {e}")
    
    def _compute_hash(self, config: Dict[str, Any]) -> str:
        """Compute hash of risk configuration for change detection"""
        # Sort keys for consistent hashing
        config_str = json.dumps(config, sort_keys=True)
        return hashlib.sha256(config_str.encode()).hexdigest()
    
    def set_baseline(self, risk_config: Dict[str, Any]):
        """
        Set the baseline risk configuration
        
        This should be called once to establish the approved baseline.
        All future configurations will be compared against this.
        
        Args:
            risk_config: Approved risk configuration dictionary
        """
        self.baseline_config = risk_config
        self.baseline_hash = self._compute_hash(risk_config)
        
        # Save to disk
        with open(self.baseline_config_path, 'w') as f:
            json.dump(risk_config, f, indent=2)
        
        logger.info(f"🔒 Set baseline risk config (hash: {self.baseline_hash[:8]})")
    
    def validate_config(
        self,
        current_config: Dict[str, Any],
        allow_emergency_override: bool = False
    ) -> bool:
        """
        Validate current risk configuration against baseline
        
        Args:
            current_config: Current risk configuration to validate
            allow_emergency_override: If True, allows emergency overrides
            
        Returns:
            True if configuration is approved, raises RiskFreezeViolation otherwise
        """
        if self.baseline_config is None:
            logger.warning("⚠️  No baseline config set - treating as first run")
            self.set_baseline(current_config)
            return True
        
        # Check if config has changed
        current_hash = self._compute_hash(current_config)
        
        if current_hash == self.baseline_hash:
            logger.debug("✅ Risk config unchanged")
            return True
        
        # Config has changed - check what changed
        changes = self._detect_changes(self.baseline_config, current_config)
        
        if not changes:
            # Hash changed but no meaningful changes (e.g., formatting)
            logger.debug("Config hash changed but no parameter changes detected")
            return True
        
        # Changes detected - this is a RISK FREEZE violation
        protected_changes = [
            change for change in changes
            if change['parameter'] in self.PROTECTED_PARAMETERS
        ]
        
        if not protected_changes:
            # Only non-protected parameters changed
            logger.warning(f"⚠️  {len(changes)} non-protected risk parameters changed")
            for change in changes:
                logger.warning(f"   - {change['parameter']}: {change['old_value']} → {change['new_value']}")
            return True
        
        # Protected parameters changed - VIOLATION
        violation_msg = self._format_violation_message(protected_changes)
        
        if allow_emergency_override:
            logger.critical("🚨 RISK FREEZE VIOLATION with emergency override allowed")
            logger.critical(violation_msg)
            logger.critical("⚠️  This change requires post-emergency approval within 48 hours!")
            return True
        
        # No override - raise violation
        logger.critical("🚨 RISK FREEZE VIOLATION DETECTED!")
        logger.critical(violation_msg)
        raise RiskFreezeViolation(violation_msg)
    
    def _detect_changes(
        self,
        baseline: Dict[str, Any],
        current: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Detect changes between baseline and current config"""
        changes = []
        
        # Check all keys in either config
        all_keys = set(baseline.keys()) | set(current.keys())
        
        for key in all_keys:
            baseline_value = baseline.get(key)
            current_value = current.get(key)
            
            if baseline_value != current_value:
                changes.append({
                    'parameter': key,
                    'old_value': baseline_value,
                    'new_value': current_value,
                    'is_protected': key in self.PROTECTED_PARAMETERS
                })
        
        return changes
    
    def _format_violation_message(self, changes: List[Dict[str, Any]]) -> str:
        """Format a violation message"""
        lines = [
            "=" * 80,
            "🚨 RISK FREEZE POLICY VIOLATION",
            "=" * 80,
            "",
            "The following PROTECTED risk parameters were changed without approval:",
            ""
        ]
        
        for change in changes:
            lines.append(f"  ❌ {change['parameter']}")
            lines.append(f"     Old: {change['old_value']}")
            lines.append(f"     New: {change['new_value']}")
            lines.append("")
        
        lines.extend([
            "⚠️  All risk parameter changes require:",
            "   1. Backtesting (minimum 3 months)",
            "   2. Paper Trading (minimum 2 weeks)",
            "   3. Version documentation",
            "   4. Multi-stakeholder approval",
            "",
            "See RISK_FREEZE_POLICY.md for the full approval process.",
            "",
            "=" * 80
        ])
        
        return "\n".join(lines)
    
    def declare_emergency_override(
        self,
        reason: str,
        authorized_by: str,
        parameters_changed: List[str]
    ):
        """
        Declare an emergency override of RISK FREEZE
        
        Use ONLY for critical situations (see RISK_FREEZE_POLICY.md).
        Requires post-emergency approval within 48 hours.
        
        Args:
            reason: Emergency reason (e.g., "Exchange margin requirement changed")
            authorized_by: Person authorizing override (e.g., "Technical Lead")
            parameters_changed: List of parameters being changed
        """
        override = EmergencyOverride(
            reason=reason,
            authorized_by=authorized_by,
            parameters_changed=parameters_changed
        )
        
        self.emergency_overrides.append(override)
        self._save_emergency_log()
        
        logger.critical("🚨 EMERGENCY RISK FREEZE OVERRIDE DECLARED")
        logger.critical(f"   Reason: {reason}")
        logger.critical(f"   Authorized by: {authorized_by}")
        logger.critical(f"   Parameters: {', '.join(parameters_changed)}")
        logger.critical("   ⚠️  Post-emergency approval required within 48 hours!")
    
    def get_pending_approvals(self) -> List[EmergencyOverride]:
        """Get emergency overrides pending post-emergency approval"""
        # In a real system, this would check if approval was received
        # For now, just return all overrides
        return self.emergency_overrides
    
    def get_violation_report(self) -> str:
        """Generate a report of all RISK FREEZE activity"""
        lines = [
            "Risk Freeze Guard - Activity Report",
            "=" * 80,
            f"Generated: {datetime.utcnow().isoformat()}",
            "",
            f"Baseline Config Hash: {self.baseline_hash[:16] if self.baseline_hash else 'None'}",
            f"Emergency Overrides: {len(self.emergency_overrides)}",
            ""
        ]
        
        if self.emergency_overrides:
            lines.append("Emergency Overrides:")
            lines.append("-" * 80)
            for i, override in enumerate(self.emergency_overrides, 1):
                lines.append(f"{i}. {override.timestamp}")
                lines.append(f"   Reason: {override.reason}")
                lines.append(f"   Authorized by: {override.authorized_by}")
                lines.append(f"   Parameters: {', '.join(override.parameters_changed)}")
                lines.append("")
        
        return "\n".join(lines)


# Global singleton
_guard: Optional[RiskFreezeGuard] = None


def get_risk_freeze_guard() -> RiskFreezeGuard:
    """Get or create the global Risk Freeze Guard"""
    global _guard
    if _guard is None:
        _guard = RiskFreezeGuard()
    return _guard


def enforce_risk_freeze(risk_config: Dict[str, Any]):
    """
    Convenience function to enforce risk freeze on a configuration
    
    Args:
        risk_config: Risk configuration to validate
        
    Raises:
        RiskFreezeViolation: If configuration violates RISK FREEZE policy
    """
    guard = get_risk_freeze_guard()
    guard.validate_config(risk_config)
