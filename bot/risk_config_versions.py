"""
Risk Configuration Versioning System

Manages versioned risk configurations to enforce RISK FREEZE policy.
All risk parameter changes must go through version control with proper approval.

Author: NIJA Trading Systems
Date: February 12, 2026
"""

import json
import logging
from datetime import datetime
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict
from pathlib import Path

logger = logging.getLogger("nija.risk_config_versions")


@dataclass
class RiskParameterChange:
    """Represents a single risk parameter change"""
    parameter: str
    old_value: Any
    new_value: Any
    reason: str


@dataclass
class BacktestResults:
    """Backtest validation results"""
    period_start: str
    period_end: str
    win_rate: float
    max_drawdown: float
    sharpe_ratio: float
    total_return: float
    total_trades: int
    conclusion: str


@dataclass
class PaperTradingResults:
    """Paper trading validation results"""
    period_start: str
    period_end: str
    trades: int
    win_rate: float
    max_drawdown: float
    conclusion: str


@dataclass
class Approval:
    """Approval signature"""
    role: str
    name: str
    date: str
    signature: str


@dataclass
class RiskConfigVersion:
    """
    Versioned risk configuration with full approval metadata
    
    Version format: RISK_CONFIG_v{MAJOR}.{MINOR}.{PATCH}
    - MAJOR: Breaking changes to risk model
    - MINOR: New risk rules or significant adjustments
    - PATCH: Minor parameter tuning
    """
    version: str
    date: str
    author: str
    status: str  # proposed, testing, approved, active, deprecated
    changes: List[RiskParameterChange]
    backtesting: Optional[BacktestResults]
    paper_trading: Optional[PaperTradingResults]
    approvals: List[Approval]
    risk_parameters: Dict[str, Any]
    
    def is_approved(self) -> bool:
        """Check if version has all required approvals"""
        required_roles = {'Technical Lead', 'Risk Manager', 'Strategy Developer'}
        approved_roles = {approval.role for approval in self.approvals}
        return required_roles.issubset(approved_roles)
    
    def can_activate(self) -> bool:
        """Check if version can be activated"""
        return (
            self.status in ['approved', 'active'] and
            self.is_approved() and
            self.backtesting is not None and
            self.paper_trading is not None
        )
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for serialization"""
        return {
            'version': self.version,
            'date': self.date,
            'author': self.author,
            'status': self.status,
            'changes': [asdict(change) for change in self.changes],
            'backtesting': asdict(self.backtesting) if self.backtesting else None,
            'paper_trading': asdict(self.paper_trading) if self.paper_trading else None,
            'approvals': [asdict(approval) for approval in self.approvals],
            'risk_parameters': self.risk_parameters
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'RiskConfigVersion':
        """Create from dictionary"""
        return cls(
            version=data['version'],
            date=data['date'],
            author=data['author'],
            status=data['status'],
            changes=[RiskParameterChange(**change) for change in data['changes']],
            backtesting=BacktestResults(**data['backtesting']) if data.get('backtesting') else None,
            paper_trading=PaperTradingResults(**data['paper_trading']) if data.get('paper_trading') else None,
            approvals=[Approval(**approval) for approval in data['approvals']],
            risk_parameters=data['risk_parameters']
        )


class RiskConfigVersionManager:
    """
    Manages risk configuration versions and enforces RISK FREEZE policy
    """
    
    def __init__(self, config_dir: str = "config/risk_versions"):
        """
        Initialize version manager
        
        Args:
            config_dir: Directory to store risk configuration versions
        """
        self.config_dir = Path(config_dir)
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.versions: Dict[str, RiskConfigVersion] = {}
        self._load_all_versions()
    
    def _load_all_versions(self):
        """Load all risk configuration versions from disk"""
        for version_file in self.config_dir.glob("RISK_CONFIG_v*.json"):
            try:
                with open(version_file, 'r') as f:
                    data = json.load(f)
                    version = RiskConfigVersion.from_dict(data)
                    self.versions[version.version] = version
                    logger.info(f"Loaded risk config version: {version.version}")
            except Exception as e:
                logger.error(f"Failed to load {version_file}: {e}")
    
    def create_version(
        self,
        version: str,
        author: str,
        changes: List[RiskParameterChange],
        risk_parameters: Dict[str, Any]
    ) -> RiskConfigVersion:
        """
        Create a new risk configuration version
        
        Args:
            version: Version string (e.g., "RISK_CONFIG_v1.1.0")
            author: Person proposing the change
            changes: List of parameter changes
            risk_parameters: Complete risk parameter dictionary
            
        Returns:
            New RiskConfigVersion in 'proposed' status
        """
        if version in self.versions:
            raise ValueError(f"Version {version} already exists")
        
        config = RiskConfigVersion(
            version=version,
            date=datetime.utcnow().isoformat(),
            author=author,
            status='proposed',
            changes=changes,
            backtesting=None,
            paper_trading=None,
            approvals=[],
            risk_parameters=risk_parameters
        )
        
        self.versions[version] = config
        self._save_version(config)
        
        logger.info(f"Created new risk config version: {version}")
        return config
    
    def add_backtest_results(
        self,
        version: str,
        results: BacktestResults
    ):
        """Add backtest results to a version"""
        if version not in self.versions:
            raise ValueError(f"Version {version} not found")
        
        config = self.versions[version]
        config.backtesting = results
        config.status = 'testing'
        self._save_version(config)
        
        logger.info(f"Added backtest results to {version}")
    
    def add_paper_trading_results(
        self,
        version: str,
        results: PaperTradingResults
    ):
        """Add paper trading results to a version"""
        if version not in self.versions:
            raise ValueError(f"Version {version} not found")
        
        config = self.versions[version]
        config.paper_trading = results
        self._save_version(config)
        
        logger.info(f"Added paper trading results to {version}")
    
    def add_approval(
        self,
        version: str,
        approval: Approval
    ):
        """Add an approval signature to a version"""
        if version not in self.versions:
            raise ValueError(f"Version {version} not found")
        
        config = self.versions[version]
        
        # Check for duplicate role
        existing_roles = {a.role for a in config.approvals}
        if approval.role in existing_roles:
            logger.warning(f"Replacing existing approval from {approval.role}")
            config.approvals = [a for a in config.approvals if a.role != approval.role]
        
        config.approvals.append(approval)
        
        # Update status if fully approved
        if config.is_approved() and config.backtesting and config.paper_trading:
            config.status = 'approved'
        
        self._save_version(config)
        logger.info(f"Added {approval.role} approval to {version}")
    
    def activate_version(self, version: str):
        """
        Activate a risk configuration version
        
        This makes it the active configuration for trading.
        Requires full approval and testing.
        """
        if version not in self.versions:
            raise ValueError(f"Version {version} not found")
        
        config = self.versions[version]
        
        if not config.can_activate():
            missing = []
            if not config.is_approved():
                missing.append("approvals")
            if not config.backtesting:
                missing.append("backtesting")
            if not config.paper_trading:
                missing.append("paper trading")
            raise ValueError(f"Cannot activate {version}. Missing: {', '.join(missing)}")
        
        # Deactivate current active version
        for v in self.versions.values():
            if v.status == 'active':
                v.status = 'deprecated'
                self._save_version(v)
        
        # Activate new version
        config.status = 'active'
        self._save_version(config)
        
        logger.info(f"✅ Activated risk config version: {version}")
    
    def get_active_version(self) -> Optional[RiskConfigVersion]:
        """Get the currently active risk configuration version"""
        for version in self.versions.values():
            if version.status == 'active':
                return version
        return None
    
    def get_active_parameters(self) -> Dict[str, Any]:
        """Get risk parameters from active version"""
        active = self.get_active_version()
        if not active:
            logger.warning("No active risk configuration version found")
            return {}
        return active.risk_parameters
    
    def get_version(self, version: str) -> Optional[RiskConfigVersion]:
        """Get a specific version"""
        return self.versions.get(version)
    
    def list_versions(self) -> List[RiskConfigVersion]:
        """List all versions"""
        return sorted(self.versions.values(), key=lambda v: v.date, reverse=True)
    
    def _save_version(self, config: RiskConfigVersion):
        """Save version to disk"""
        filepath = self.config_dir / f"{config.version}.json"
        with open(filepath, 'w') as f:
            json.dump(config.to_dict(), f, indent=2)
    
    def validate_change(
        self,
        old_params: Dict[str, Any],
        new_params: Dict[str, Any]
    ) -> List[RiskParameterChange]:
        """
        Validate and document parameter changes
        
        Args:
            old_params: Current risk parameters
            new_params: Proposed risk parameters
            
        Returns:
            List of changes detected
        """
        changes = []
        
        # Find all changed parameters
        all_keys = set(old_params.keys()) | set(new_params.keys())
        
        for key in all_keys:
            old_value = old_params.get(key)
            new_value = new_params.get(key)
            
            if old_value != new_value:
                changes.append(RiskParameterChange(
                    parameter=key,
                    old_value=old_value,
                    new_value=new_value,
                    reason="Pending documentation"
                ))
        
        if changes:
            logger.warning(f"⚠️  RISK FREEZE VIOLATION: {len(changes)} risk parameter(s) changed without approval!")
            for change in changes:
                logger.warning(f"   - {change.parameter}: {change.old_value} → {change.new_value}")
        
        return changes
    
    def generate_version_report(self, version: str) -> str:
        """Generate a human-readable report for a version"""
        config = self.get_version(version)
        if not config:
            return f"Version {version} not found"
        
        report = []
        report.append(f"Risk Configuration Version Report")
        report.append("=" * 60)
        report.append(f"Version: {config.version}")
        report.append(f"Date: {config.date}")
        report.append(f"Author: {config.author}")
        report.append(f"Status: {config.status}")
        report.append("")
        
        report.append("Changes:")
        report.append("-" * 60)
        for change in config.changes:
            report.append(f"  • {change.parameter}")
            report.append(f"    Old: {change.old_value}")
            report.append(f"    New: {change.new_value}")
            report.append(f"    Reason: {change.reason}")
        report.append("")
        
        if config.backtesting:
            bt = config.backtesting
            report.append("Backtest Results:")
            report.append("-" * 60)
            report.append(f"  Period: {bt.period_start} to {bt.period_end}")
            report.append(f"  Win Rate: {bt.win_rate:.2%}")
            report.append(f"  Max Drawdown: {bt.max_drawdown:.2%}")
            report.append(f"  Sharpe Ratio: {bt.sharpe_ratio:.2f}")
            report.append(f"  Total Return: {bt.total_return:.2%}")
            report.append(f"  Total Trades: {bt.total_trades}")
            report.append(f"  Conclusion: {bt.conclusion}")
            report.append("")
        
        if config.paper_trading:
            pt = config.paper_trading
            report.append("Paper Trading Results:")
            report.append("-" * 60)
            report.append(f"  Period: {pt.period_start} to {pt.period_end}")
            report.append(f"  Trades: {pt.trades}")
            report.append(f"  Win Rate: {pt.win_rate:.2%}")
            report.append(f"  Max Drawdown: {pt.max_drawdown:.2%}")
            report.append(f"  Conclusion: {pt.conclusion}")
            report.append("")
        
        report.append("Approvals:")
        report.append("-" * 60)
        if config.approvals:
            for approval in config.approvals:
                report.append(f"  ✅ {approval.role}: {approval.name} ({approval.date})")
        else:
            report.append("  ⚠️  No approvals yet")
        
        report.append("")
        report.append(f"Can Activate: {'✅ Yes' if config.can_activate() else '❌ No'}")
        
        return "\n".join(report)


# Singleton instance for global access
_version_manager: Optional[RiskConfigVersionManager] = None


def get_version_manager() -> RiskConfigVersionManager:
    """Get or create the global risk configuration version manager"""
    global _version_manager
    if _version_manager is None:
        _version_manager = RiskConfigVersionManager()
    return _version_manager
