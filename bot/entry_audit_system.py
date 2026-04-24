"""
NIJA Entry Audit System (Phase 1: The Brain)

Comprehensive entry validation and audit logging system.
Tracks every entry decision with detailed hierarchical validation.

Features:
- Hierarchical validation tracking (confidence → score → filters → execution)
- Rejection reason categorization with explicit codes
- Win/loss attribution to entry signal type
- Entry quality metrics and analytics
- Signal hierarchy tracking (which indicator triggered entry)
- Liquidity and spread validation
- Slippage tolerance checks
- Double-entry prevention
- Entry reason logging for analytics and debugging

Author: NIJA Trading Systems
Version: 1.0
Date: February 18, 2026
"""

import json
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict
from enum import Enum
from pathlib import Path

logger = logging.getLogger("nija.entry_audit")


class EntryTrigger(Enum):
    """Primary indicator that triggered the entry signal"""
    RSI_OVERSOLD = "RSI_OVERSOLD"
    RSI_OVERBOUGHT = "RSI_OVERBOUGHT"
    VWAP_PULLBACK = "VWAP_PULLBACK"
    MACD_CROSS = "MACD_CROSS"
    EMA_PULLBACK = "EMA_PULLBACK"
    VOLUME_SPIKE = "VOLUME_SPIKE"
    BOLLINGER_BOUNCE = "BOLLINGER_BOUNCE"
    ADX_TREND = "ADX_TREND"
    MULTI_FACTOR = "MULTI_FACTOR"
    UNKNOWN = "UNKNOWN"


class EntryQuality(Enum):
    """Entry quality classification"""
    EXCELLENT = "EXCELLENT"  # 90-100% confidence
    GOOD = "GOOD"            # 75-89% confidence
    ACCEPTABLE = "ACCEPTABLE" # 60-74% confidence
    MARGINAL = "MARGINAL"    # 50-59% confidence
    POOR = "POOR"            # <50% confidence


class RejectionCategory(Enum):
    """High-level categorization of rejection reasons"""
    SIGNAL_QUALITY = "SIGNAL_QUALITY"
    CAPITAL_CONSTRAINT = "CAPITAL_CONSTRAINT"
    POSITION_LIMIT = "POSITION_LIMIT"
    RISK_MANAGEMENT = "RISK_MANAGEMENT"
    MARKET_CONDITIONS = "MARKET_CONDITIONS"
    LIQUIDITY = "LIQUIDITY"
    TECHNICAL_ERROR = "TECHNICAL_ERROR"


@dataclass
class SignalHierarchy:
    """Tracks which signals contributed to entry decision"""
    primary_trigger: EntryTrigger
    rsi_contribution: float = 0.0
    vwap_contribution: float = 0.0
    macd_contribution: float = 0.0
    ema_contribution: float = 0.0
    volume_contribution: float = 0.0
    adx_contribution: float = 0.0
    bollinger_contribution: float = 0.0
    
    def get_top_contributors(self, top_n: int = 3) -> List[Tuple[str, float]]:
        """Returns top N contributors by score"""
        contributions = {
            'RSI': self.rsi_contribution,
            'VWAP': self.vwap_contribution,
            'MACD': self.macd_contribution,
            'EMA': self.ema_contribution,
            'Volume': self.volume_contribution,
            'ADX': self.adx_contribution,
            'Bollinger': self.bollinger_contribution,
        }
        sorted_contrib = sorted(contributions.items(), key=lambda x: x[1], reverse=True)
        return sorted_contrib[:top_n]


@dataclass
class EntryValidationStep:
    """Individual validation step result"""
    step_name: str
    passed: bool
    value: Optional[float]
    threshold: Optional[float]
    reason: Optional[str]
    timestamp: datetime


@dataclass
class LiquidityCheck:
    """Liquidity and spread validation"""
    bid_ask_spread_pct: float
    spread_acceptable: bool
    volume_24h: float
    volume_acceptable: bool
    order_book_depth: Optional[float]
    liquidity_score: float  # 0-100
    
    def is_valid(self) -> bool:
        """Check if liquidity is acceptable"""
        return self.spread_acceptable and self.volume_acceptable and self.liquidity_score >= 50.0


@dataclass
class SlippageEstimate:
    """Slippage tolerance and estimation"""
    expected_price: float
    max_acceptable_slippage_pct: float
    estimated_slippage_pct: float
    slippage_acceptable: bool
    
    def is_valid(self) -> bool:
        """Check if slippage is acceptable"""
        return self.slippage_acceptable


@dataclass
class EntryAuditRecord:
    """Comprehensive entry audit record"""
    # Identification
    audit_id: str
    timestamp: datetime
    symbol: str
    signal_type: str  # LONG or SHORT
    
    # Entry Decision
    entry_allowed: bool
    rejection_code: Optional[str]
    rejection_category: Optional[RejectionCategory]
    rejection_message: Optional[str]
    
    # Signal Analysis
    signal_hierarchy: SignalHierarchy
    entry_quality: EntryQuality
    confidence_score: float
    entry_score: float
    
    # Validation Steps
    validation_steps: List[EntryValidationStep]
    
    # Risk Calculation
    proposed_size_usd: float
    risk_per_trade_pct: float
    stop_loss_price: Optional[float]
    stop_loss_pct: Optional[float]
    
    # Liquidity & Spread
    liquidity_check: Optional[LiquidityCheck]
    slippage_estimate: Optional[SlippageEstimate]
    
    # Market Context
    price: float
    adx: Optional[float]
    rsi: Optional[float]
    volume_24h: Optional[float]
    
    # Account Context
    account_balance: float
    tier_name: str
    position_count: int
    max_positions: int
    
    # Execution (if entry allowed)
    executed: bool = False
    execution_price: Optional[float] = None
    execution_timestamp: Optional[datetime] = None
    actual_slippage_pct: Optional[float] = None
    
    # Outcome Tracking (populated later)
    outcome_tracked: bool = False
    closed_at: Optional[datetime] = None
    exit_price: Optional[float] = None
    pnl_usd: Optional[float] = None
    pnl_pct: Optional[float] = None
    win: Optional[bool] = None
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for JSON serialization"""
        result = asdict(self)
        # Convert enums to strings
        result['rejection_category'] = self.rejection_category.value if self.rejection_category else None
        result['signal_hierarchy']['primary_trigger'] = self.signal_hierarchy.primary_trigger.value
        result['entry_quality'] = self.entry_quality.value
        # Convert datetime to ISO format
        result['timestamp'] = self.timestamp.isoformat()
        if self.execution_timestamp:
            result['execution_timestamp'] = self.execution_timestamp.isoformat()
        if self.closed_at:
            result['closed_at'] = self.closed_at.isoformat()
        # Convert validation steps
        result['validation_steps'] = [
            {
                'step_name': step.step_name,
                'passed': step.passed,
                'value': step.value,
                'threshold': step.threshold,
                'reason': step.reason,
                'timestamp': step.timestamp.isoformat()
            }
            for step in self.validation_steps
        ]
        return result


class EntryAuditSystem:
    """
    Manages comprehensive entry audit logging and analytics.
    
    Provides:
    - Detailed entry validation tracking
    - Rejection reason analytics
    - Win/loss attribution by signal type
    - Entry quality metrics
    - Liquidity and slippage tracking
    """
    
    def __init__(self, data_dir: str = "./data"):
        """Initialize the entry audit system"""
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(exist_ok=True)
        
        self.audit_file = self.data_dir / "entry_audit_log.jsonl"
        self.stats_file = self.data_dir / "entry_audit_stats.json"
        
        # In-memory tracking
        self.recent_audits: List[EntryAuditRecord] = []
        self.max_recent = 1000
        
        # Statistics
        self.stats = self._load_stats()
        
        logger.info(f"📊 Entry Audit System initialized - Logging to {self.audit_file}")
    
    def _load_stats(self) -> Dict:
        """Load statistics from disk"""
        if self.stats_file.exists():
            try:
                with open(self.stats_file, 'r') as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"Could not load stats: {e}")
        
        return {
            'total_signals': 0,
            'total_accepted': 0,
            'total_rejected': 0,
            'rejection_reasons': {},
            'signal_triggers': {},
            'quality_distribution': {},
            'win_loss_by_trigger': {},
            'avg_confidence_by_outcome': {},
        }
    
    def _save_stats(self):
        """Save statistics to disk"""
        try:
            with open(self.stats_file, 'w') as f:
                json.dump(self.stats, f, indent=2)
        except Exception as e:
            logger.error(f"Could not save stats: {e}")
    
    def log_entry_decision(self, record: EntryAuditRecord):
        """
        Log an entry decision (accepted or rejected).
        
        Args:
            record: Complete entry audit record
        """
        # Add to recent audits
        self.recent_audits.append(record)
        if len(self.recent_audits) > self.max_recent:
            self.recent_audits.pop(0)
        
        # Update statistics
        self._update_stats(record)
        
        # Write to disk (append to JSONL file)
        self._append_to_log(record)
        
        # Log summary
        self._log_summary(record)
    
    def _update_stats(self, record: EntryAuditRecord):
        """Update statistics with new record"""
        stats = self.stats
        stats['total_signals'] += 1
        
        if record.entry_allowed:
            stats['total_accepted'] += 1
        else:
            stats['total_rejected'] += 1
            
            # Track rejection reasons
            if record.rejection_code:
                if record.rejection_code not in stats['rejection_reasons']:
                    stats['rejection_reasons'][record.rejection_code] = 0
                stats['rejection_reasons'][record.rejection_code] += 1
        
        # Track signal triggers
        trigger = record.signal_hierarchy.primary_trigger.value
        if trigger not in stats['signal_triggers']:
            stats['signal_triggers'][trigger] = {'count': 0, 'accepted': 0, 'wins': 0, 'losses': 0}
        stats['signal_triggers'][trigger]['count'] += 1
        if record.entry_allowed:
            stats['signal_triggers'][trigger]['accepted'] += 1
        
        # Track quality distribution
        quality = record.entry_quality.value
        if quality not in stats['quality_distribution']:
            stats['quality_distribution'][quality] = 0
        stats['quality_distribution'][quality] += 1
        
        self._save_stats()
    
    def _append_to_log(self, record: EntryAuditRecord):
        """Append record to JSONL log file"""
        try:
            with open(self.audit_file, 'a') as f:
                f.write(json.dumps(record.to_dict()) + '\n')
        except Exception as e:
            logger.error(f"Could not write to audit log: {e}")
    
    def _log_summary(self, record: EntryAuditRecord):
        """Log a human-readable summary"""
        if record.entry_allowed:
            top_contributors = record.signal_hierarchy.get_top_contributors(3)
            contrib_str = ", ".join([f"{name}:{score:.2f}" for name, score in top_contributors])
            
            logger.info(
                f"✅ ENTRY APPROVED: {record.symbol} {record.signal_type} | "
                f"Quality: {record.entry_quality.value} | "
                f"Confidence: {record.confidence_score:.2f} | "
                f"Score: {record.entry_score:.2f} | "
                f"Size: ${record.proposed_size_usd:.2f} | "
                f"Primary: {record.signal_hierarchy.primary_trigger.value} | "
                f"Top: {contrib_str}"
            )
        else:
            logger.info(
                f"❌ ENTRY REJECTED: {record.symbol} {record.signal_type} | "
                f"Reason: {record.rejection_code} | "
                f"Category: {record.rejection_category.value if record.rejection_category else 'UNKNOWN'} | "
                f"Message: {record.rejection_message} | "
                f"Confidence: {record.confidence_score:.2f}"
            )
    
    def update_outcome(self, audit_id: str, exit_price: float, pnl_usd: float, 
                      closed_at: datetime):
        """
        Update entry record with trade outcome.
        
        Args:
            audit_id: Audit record ID
            exit_price: Exit price
            pnl_usd: Profit/loss in USD
            closed_at: Close timestamp
        """
        # Find record in recent audits
        for record in self.recent_audits:
            if record.audit_id == audit_id:
                record.outcome_tracked = True
                record.closed_at = closed_at
                record.exit_price = exit_price
                record.pnl_usd = pnl_usd
                record.pnl_pct = (pnl_usd / record.proposed_size_usd) * 100 if record.proposed_size_usd > 0 else 0
                record.win = pnl_usd > 0
                
                # Update statistics
                trigger = record.signal_hierarchy.primary_trigger.value
                if trigger in self.stats['signal_triggers']:
                    if record.win:
                        self.stats['signal_triggers'][trigger]['wins'] += 1
                    else:
                        self.stats['signal_triggers'][trigger]['losses'] += 1
                
                self._save_stats()
                
                logger.info(
                    f"📈 OUTCOME RECORDED: {record.symbol} | "
                    f"Trigger: {trigger} | "
                    f"Result: {'WIN' if record.win else 'LOSS'} | "
                    f"P&L: ${pnl_usd:.2f} ({record.pnl_pct:.2f}%)"
                )
                break
    
    def get_stats_summary(self) -> Dict:
        """Get current statistics summary"""
        stats = self.stats.copy()
        
        # Calculate acceptance rate
        if stats['total_signals'] > 0:
            stats['acceptance_rate'] = stats['total_accepted'] / stats['total_signals']
            stats['rejection_rate'] = stats['total_rejected'] / stats['total_signals']
        else:
            stats['acceptance_rate'] = 0.0
            stats['rejection_rate'] = 0.0
        
        # Calculate win rates by trigger
        stats['win_rates_by_trigger'] = {}
        for trigger, data in stats['signal_triggers'].items():
            total_completed = data['wins'] + data['losses']
            if total_completed > 0:
                win_rate = data['wins'] / total_completed
                stats['win_rates_by_trigger'][trigger] = {
                    'win_rate': win_rate,
                    'total_trades': total_completed,
                    'wins': data['wins'],
                    'losses': data['losses'],
                    'acceptance_rate': data['accepted'] / data['count'] if data['count'] > 0 else 0
                }
        
        return stats
    
    def get_top_rejection_reasons(self, top_n: int = 10) -> List[Tuple[str, int]]:
        """Get top N rejection reasons"""
        reasons = self.stats['rejection_reasons']
        sorted_reasons = sorted(reasons.items(), key=lambda x: x[1], reverse=True)
        return sorted_reasons[:top_n]
    
    def check_duplicate_entry(self, symbol: str, lookback_minutes: int = 5) -> bool:
        """
        Check if there was a recent entry attempt for the same symbol.
        
        Args:
            symbol: Trading symbol
            lookback_minutes: How far back to check
            
        Returns:
            True if duplicate detected, False otherwise
        """
        cutoff_time = datetime.now() - timedelta(minutes=lookback_minutes)
        
        for record in reversed(self.recent_audits):
            if record.timestamp < cutoff_time:
                break
            
            if record.symbol == symbol and record.entry_allowed:
                logger.warning(
                    f"⚠️ DUPLICATE ENTRY DETECTED: {symbol} | "
                    f"Previous entry {(datetime.now() - record.timestamp).total_seconds():.0f}s ago"
                )
                return True
        
        return False
    
    def print_daily_summary(self):
        """Print daily entry audit summary"""
        today = datetime.now().date()
        today_records = [
            r for r in self.recent_audits 
            if r.timestamp.date() == today
        ]
        
        if not today_records:
            logger.info("📊 No entry signals today")
            return
        
        accepted = sum(1 for r in today_records if r.entry_allowed)
        rejected = len(today_records) - accepted
        
        logger.info(f"\n{'='*60}")
        logger.info(f"📊 DAILY ENTRY AUDIT SUMMARY - {today}")
        logger.info(f"{'='*60}")
        logger.info(f"Total Signals: {len(today_records)}")
        logger.info(f"Accepted: {accepted} ({accepted/len(today_records)*100:.1f}%)")
        logger.info(f"Rejected: {rejected} ({rejected/len(today_records)*100:.1f}%)")
        
        if rejected > 0:
            logger.info(f"\nTop Rejection Reasons:")
            rejection_counts = {}
            for r in today_records:
                if not r.entry_allowed and r.rejection_code:
                    rejection_counts[r.rejection_code] = rejection_counts.get(r.rejection_code, 0) + 1
            
            for reason, count in sorted(rejection_counts.items(), key=lambda x: x[1], reverse=True)[:5]:
                logger.info(f"  {reason}: {count}")
        
        logger.info(f"{'='*60}\n")


# Global instance
_entry_audit_system = None


def get_entry_audit_system() -> EntryAuditSystem:
    """Get global entry audit system instance"""
    global _entry_audit_system
    if _entry_audit_system is None:
        _entry_audit_system = EntryAuditSystem()
    return _entry_audit_system
