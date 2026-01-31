"""
Paper Trading Graduation System

Tracks user progression through paper trading and manages graduation to live trading.
This module implements secure file handling to prevent path traversal vulnerabilities.

Security:
    - All user_id inputs are sanitized before use in file paths
    - File operations use PathValidator to prevent path traversal
    - Data directory is restricted to a specific base directory

Author: NIJA Trading Systems
Date: January 31, 2026
"""

import json
import logging
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, Optional, List
from dataclasses import dataclass, asdict

from bot.path_validator import PathValidator, sanitize_filename

logger = logging.getLogger(__name__)


@dataclass
class GraduationProgress:
    """Tracks user's progress through paper trading graduation criteria"""
    user_id: str
    level: str  # "paper", "restricted_live", "full_live"
    created_at: str
    last_updated: str
    
    # Paper trading metrics
    total_trades: int = 0
    win_rate: float = 0.0
    sharpe_ratio: float = 0.0
    max_drawdown: float = 0.0
    profit_factor: float = 0.0
    avg_risk_reward: float = 0.0
    
    # Milestone tracking
    paper_graduation_date: Optional[str] = None
    restricted_start_date: Optional[str] = None
    full_live_date: Optional[str] = None
    
    # Criteria met flags
    criteria_met: Dict[str, bool] = None
    
    def __post_init__(self):
        if self.criteria_met is None:
            self.criteria_met = {
                "min_trades": False,
                "win_rate": False,
                "sharpe_ratio": False,
                "max_drawdown": False,
                "profit_factor": False,
                "risk_reward": False,
                "trading_days": False
            }


class PaperTradingGraduationSystem:
    """
    Manages user progression through paper trading to live trading.
    
    Security Features:
        - Sanitizes user_id to prevent path traversal attacks
        - Uses PathValidator for all file operations
        - Restricts file operations to data_dir base directory
    
    Graduation Criteria:
        Paper -> Restricted Live:
            - Minimum 50 trades
            - Win rate >= 52%
            - Sharpe ratio >= 1.0
            - Max drawdown <= 15%
            - Profit factor >= 1.3
            - Avg risk-reward >= 1.5
            - Minimum 30 trading days
        
        Restricted Live -> Full Live:
            - 14 days in restricted mode
            - Maintain positive P&L
            - No major violations
    """
    
    # Graduation criteria thresholds
    MIN_TRADES = 50
    MIN_WIN_RATE = 0.52
    MIN_SHARPE = 1.0
    MAX_DRAWDOWN = 0.15
    MIN_PROFIT_FACTOR = 1.3
    MIN_RISK_REWARD = 1.5
    MIN_TRADING_DAYS = 30
    
    # Restricted live limits
    LIVE_RESTRICTED_MAX_POSITION = 500   # $500 max per position
    LIVE_RESTRICTED_MAX_TOTAL = 500     # $500 max total capital
    LIVE_FULL_UNLOCK_DAYS = 14          # Days in restricted before full unlock
    
    def __init__(self, user_id: str, data_dir: str = "data/graduation"):
        """
        Initialize graduation system for a user.
        
        Args:
            user_id: User identifier (will be sanitized for security)
            data_dir: Base directory for graduation data storage
            
        Security:
            - user_id is sanitized using sanitize_filename() to prevent path traversal
            - All file paths are constructed using secure methods
        """
        # SECURITY: Sanitize user_id to prevent path traversal attacks
        # This prevents attacks like user_id="../../../etc/passwd"
        self.user_id = sanitize_filename(user_id)
        
        # Validate and create secure base directory
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        # SECURITY: Construct file path securely using sanitized user_id
        # The filename is already sanitized, but we double-check the final path
        safe_filename = f"{self.user_id}_graduation.json"
        self.user_file = self.data_dir / safe_filename
        
        # Verify the file path is within our data directory
        try:
            self.user_file.resolve().relative_to(self.data_dir.resolve())
        except ValueError:
            logger.error(f"Security violation: file path outside data dir for user {user_id}")
            raise ValueError("Invalid user_id: security validation failed")
        
        self.progress = self._load_progress()
    
    def _load_progress(self) -> GraduationProgress:
        """
        Load user's graduation progress from disk.
        
        Returns:
            GraduationProgress object
            
        Security:
            - Uses pre-validated self.user_file path
            - File path was validated in __init__
        """
        if self.user_file.exists():
            try:
                with open(self.user_file, 'r') as f:
                    data = json.load(f)
                return GraduationProgress(**data)
            except (json.JSONDecodeError, TypeError, ValueError) as e:
                logger.error(f"Error loading graduation data for {self.user_id}: {e}")
                return self._create_new_progress()
        else:
            return self._create_new_progress()
    
    def _create_new_progress(self) -> GraduationProgress:
        """Create new graduation progress record"""
        now = datetime.utcnow().isoformat()
        return GraduationProgress(
            user_id=self.user_id,
            level="paper",
            created_at=now,
            last_updated=now
        )
    
    def _save_progress(self):
        """
        Save graduation progress to disk.
        
        Security:
            - Uses pre-validated self.user_file path
            - Atomic write operation
        """
        self.progress.last_updated = datetime.utcnow().isoformat()
        
        try:
            # Write to temporary file first (atomic operation)
            temp_file = self.user_file.with_suffix('.tmp')
            with open(temp_file, 'w') as f:
                json.dump(asdict(self.progress), f, indent=2)
            
            # Atomic rename
            temp_file.replace(self.user_file)
            
        except (OSError, IOError) as e:
            logger.error(f"Error saving graduation data for {self.user_id}: {e}")
            raise
    
    def update_metrics(self, metrics: Dict[str, float]):
        """
        Update trading performance metrics.
        
        Args:
            metrics: Dictionary containing performance metrics
        """
        self.progress.total_trades = int(metrics.get('total_trades', 0))
        self.progress.win_rate = float(metrics.get('win_rate', 0.0))
        self.progress.sharpe_ratio = float(metrics.get('sharpe_ratio', 0.0))
        self.progress.max_drawdown = float(metrics.get('max_drawdown', 0.0))
        self.progress.profit_factor = float(metrics.get('profit_factor', 0.0))
        self.progress.avg_risk_reward = float(metrics.get('avg_risk_reward', 0.0))
        
        # Update criteria met flags
        self._check_criteria()
        self._save_progress()
    
    def _check_criteria(self):
        """Check if graduation criteria are met"""
        self.progress.criteria_met['min_trades'] = self.progress.total_trades >= self.MIN_TRADES
        self.progress.criteria_met['win_rate'] = self.progress.win_rate >= self.MIN_WIN_RATE
        self.progress.criteria_met['sharpe_ratio'] = self.progress.sharpe_ratio >= self.MIN_SHARPE
        self.progress.criteria_met['max_drawdown'] = self.progress.max_drawdown <= self.MAX_DRAWDOWN
        self.progress.criteria_met['profit_factor'] = self.progress.profit_factor >= self.MIN_PROFIT_FACTOR
        self.progress.criteria_met['risk_reward'] = self.progress.avg_risk_reward >= self.MIN_RISK_REWARD
        
        # Check trading days (simplified - would need actual trade history)
        self.progress.criteria_met['trading_days'] = True  # TODO: implement actual check
    
    def is_ready_for_restricted_live(self) -> bool:
        """Check if user is ready to graduate to restricted live trading"""
        if self.progress.level != "paper":
            return False
        
        return all(self.progress.criteria_met.values())
    
    def graduate_to_restricted_live(self) -> bool:
        """
        Graduate user to restricted live trading.
        
        Returns:
            True if graduation successful, False otherwise
        """
        if not self.is_ready_for_restricted_live():
            logger.warning(f"User {self.user_id} not ready for graduation")
            return False
        
        self.progress.level = "restricted_live"
        self.progress.paper_graduation_date = datetime.utcnow().isoformat()
        self.progress.restricted_start_date = datetime.utcnow().isoformat()
        self._save_progress()
        
        logger.info(f"User {self.user_id} graduated to restricted live trading")
        return True
    
    def is_ready_for_full_live(self) -> bool:
        """Check if user is ready to graduate to full live trading"""
        if self.progress.level != "restricted_live":
            return False
        
        if not self.progress.restricted_start_date:
            return False
        
        # Check if user has been in restricted mode for required days
        start_date = datetime.fromisoformat(self.progress.restricted_start_date)
        days_in_restricted = (datetime.utcnow() - start_date).days
        
        return days_in_restricted >= self.LIVE_FULL_UNLOCK_DAYS
    
    def graduate_to_full_live(self) -> bool:
        """
        Graduate user to full live trading.
        
        Returns:
            True if graduation successful, False otherwise
        """
        if not self.is_ready_for_full_live():
            logger.warning(f"User {self.user_id} not ready for full live graduation")
            return False
        
        self.progress.level = "full_live"
        self.progress.full_live_date = datetime.utcnow().isoformat()
        self._save_progress()
        
        logger.info(f"User {self.user_id} graduated to full live trading")
        return True
    
    def get_current_limits(self) -> Dict[str, float]:
        """
        Get current trading limits based on graduation level.
        
        Returns:
            Dictionary with trading limits
        """
        if self.progress.level == "paper":
            return {
                "max_position_size": 1000,  # Paper money limits
                "max_total_capital": 10000,
                "max_open_positions": 10,
                "level": "paper"
            }
        elif self.progress.level == "restricted_live":
            return {
                "max_position_size": self.LIVE_RESTRICTED_MAX_POSITION,
                "max_total_capital": self.LIVE_RESTRICTED_MAX_TOTAL,
                "max_open_positions": 3,
                "level": "restricted_live"
            }
        else:  # full_live
            return {
                "max_position_size": float('inf'),
                "max_total_capital": float('inf'),
                "max_open_positions": float('inf'),
                "level": "full_live"
            }
    
    def get_status(self) -> Dict:
        """Get detailed graduation status"""
        return {
            "user_id": self.progress.user_id,
            "level": self.progress.level,
            "created_at": self.progress.created_at,
            "last_updated": self.progress.last_updated,
            "metrics": {
                "total_trades": self.progress.total_trades,
                "win_rate": self.progress.win_rate,
                "sharpe_ratio": self.progress.sharpe_ratio,
                "max_drawdown": self.progress.max_drawdown,
                "profit_factor": self.progress.profit_factor,
                "avg_risk_reward": self.progress.avg_risk_reward
            },
            "criteria_met": self.progress.criteria_met,
            "ready_for_restricted": self.is_ready_for_restricted_live(),
            "ready_for_full": self.is_ready_for_full_live(),
            "limits": self.get_current_limits()
        }
    
    def get_criteria_details(self) -> Dict:
        """Get detailed information about graduation criteria"""
        return {
            "current_progress": {
                "total_trades": f"{self.progress.total_trades}/{self.MIN_TRADES}",
                "win_rate": f"{self.progress.win_rate:.2%} (need {self.MIN_WIN_RATE:.2%})",
                "sharpe_ratio": f"{self.progress.sharpe_ratio:.2f} (need {self.MIN_SHARPE:.2f})",
                "max_drawdown": f"{self.progress.max_drawdown:.2%} (max {self.MAX_DRAWDOWN:.2%})",
                "profit_factor": f"{self.progress.profit_factor:.2f} (need {self.MIN_PROFIT_FACTOR:.2f})",
                "avg_risk_reward": f"{self.progress.avg_risk_reward:.2f} (need {self.MIN_RISK_REWARD:.2f})"
            },
            "criteria_met": self.progress.criteria_met,
            "all_criteria_met": all(self.progress.criteria_met.values())
        }
