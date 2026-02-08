"""
POSITION SCORE TELEMETRY
========================
Enhancement 2: Track why positions survive pruning

This module provides detailed telemetry on position scoring decisions,
useful for strategy tuning and understanding position lifecycle.

Author: NIJA Trading Systems
Created: February 8, 2026
"""

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional
from dataclasses import dataclass, asdict, field
from collections import defaultdict
import threading

logger = logging.getLogger("nija.position_telemetry")


@dataclass
class PositionScoreRecord:
    """Record of a position's score at a point in time"""
    timestamp: datetime
    symbol: str
    score: float
    pnl_pct: float
    age_hours: float
    stagnation_hours: float
    
    # Score breakdown
    pnl_contribution: float = 0.0
    stagnation_contribution: float = 0.0
    age_contribution: float = 0.0
    
    # Decision context
    survived_pruning: bool = True
    pruning_reason: Optional[str] = None
    health_status: str = "healthy"  # healthy, unhealthy, stagnant, dust
    
    # Position details
    size_usd: float = 0.0
    entry_time: Optional[datetime] = None
    
    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization"""
        data = asdict(self)
        # Convert datetime to ISO string
        if isinstance(data['timestamp'], datetime):
            data['timestamp'] = data['timestamp'].isoformat()
        if isinstance(data.get('entry_time'), datetime):
            data['entry_time'] = data['entry_time'].isoformat()
        return data


@dataclass
class PruningEvent:
    """Record of a position being pruned/closed"""
    timestamp: datetime
    symbol: str
    reason: str
    cleanup_type: str  # DUST, CAP_EXCEEDED, UNHEALTHY, STAGNANT
    final_score: float
    final_pnl_pct: float
    size_usd: float
    age_hours: float
    
    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization"""
        data = asdict(self)
        if isinstance(data['timestamp'], datetime):
            data['timestamp'] = data['timestamp'].isoformat()
        return data


class PositionScoreTelemetry:
    """
    Position Score Telemetry System
    
    Tracks:
    - Why positions are scored the way they are
    - Why positions survive pruning
    - Why positions are closed
    - Score evolution over time
    """
    
    def __init__(self, data_dir: str = "./data"):
        """
        Initialize position score telemetry
        
        Args:
            data_dir: Directory for telemetry data files
        """
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(exist_ok=True, parents=True)
        
        # Telemetry files
        self.score_records_file = self.data_dir / "position_score_records.jsonl"
        self.pruning_events_file = self.data_dir / "position_pruning_events.jsonl"
        self.summary_file = self.data_dir / "position_telemetry_summary.json"
        
        # In-memory tracking
        self.score_history: Dict[str, List[PositionScoreRecord]] = defaultdict(list)
        self.pruning_events: List[PruningEvent] = []
        
        # Thread safety
        self._lock = threading.Lock()
        
        # Statistics
        self.stats = {
            'total_scores_recorded': 0,
            'total_pruning_events': 0,
            'positions_tracked': 0,
            'survival_count': 0,
            'pruning_reasons': defaultdict(int)
        }
        
        logger.info("✅ Position Score Telemetry initialized")
        logger.info(f"   Data directory: {self.data_dir}")
    
    def record_position_score(
        self,
        symbol: str,
        score: float,
        pnl_pct: float,
        age_hours: float,
        stagnation_hours: float,
        pnl_contribution: float = 0.0,
        stagnation_contribution: float = 0.0,
        age_contribution: float = 0.0,
        survived_pruning: bool = True,
        pruning_reason: Optional[str] = None,
        health_status: str = "healthy",
        size_usd: float = 0.0,
        entry_time: Optional[datetime] = None
    ):
        """
        Record a position's score at a point in time
        
        Args:
            symbol: Trading symbol
            score: Health score (0-100)
            pnl_pct: Current P&L percentage
            age_hours: Position age in hours
            stagnation_hours: Hours since last movement
            pnl_contribution: Score contribution from P&L
            stagnation_contribution: Score contribution from stagnation
            age_contribution: Score contribution from age
            survived_pruning: Whether position survived pruning check
            pruning_reason: Reason if position was pruned
            health_status: Overall health status
            size_usd: Position size in USD
            entry_time: Position entry time
        """
        with self._lock:
            record = PositionScoreRecord(
                timestamp=datetime.now(),
                symbol=symbol,
                score=score,
                pnl_pct=pnl_pct,
                age_hours=age_hours,
                stagnation_hours=stagnation_hours,
                pnl_contribution=pnl_contribution,
                stagnation_contribution=stagnation_contribution,
                age_contribution=age_contribution,
                survived_pruning=survived_pruning,
                pruning_reason=pruning_reason,
                health_status=health_status,
                size_usd=size_usd,
                entry_time=entry_time
            )
            
            # Add to in-memory history
            self.score_history[symbol].append(record)
            
            # Write to file (append mode)
            self._write_score_record(record)
            
            # Update statistics
            self.stats['total_scores_recorded'] += 1
            if survived_pruning:
                self.stats['survival_count'] += 1
            
            # Track unique positions
            if symbol not in self.score_history or len(self.score_history[symbol]) == 1:
                self.stats['positions_tracked'] += 1
            
            # Log notable events
            if not survived_pruning:
                logger.info(f"📊 TELEMETRY: {symbol} scored {score:.0f}/100 - PRUNED ({pruning_reason})")
            elif score < 40:
                logger.debug(f"📊 TELEMETRY: {symbol} scored {score:.0f}/100 - LOW but survived")
            elif score > 80:
                logger.debug(f"📊 TELEMETRY: {symbol} scored {score:.0f}/100 - EXCELLENT position")
    
    def record_pruning_event(
        self,
        symbol: str,
        reason: str,
        cleanup_type: str,
        final_score: float,
        final_pnl_pct: float,
        size_usd: float,
        age_hours: float
    ):
        """
        Record a position being pruned/closed
        
        Args:
            symbol: Trading symbol
            reason: Human-readable pruning reason
            cleanup_type: Type of cleanup (DUST, CAP_EXCEEDED, etc.)
            final_score: Final health score before pruning
            final_pnl_pct: Final P&L percentage
            size_usd: Position size in USD
            age_hours: Position age in hours
        """
        with self._lock:
            event = PruningEvent(
                timestamp=datetime.now(),
                symbol=symbol,
                reason=reason,
                cleanup_type=cleanup_type,
                final_score=final_score,
                final_pnl_pct=final_pnl_pct,
                size_usd=size_usd,
                age_hours=age_hours
            )
            
            # Add to in-memory list
            self.pruning_events.append(event)
            
            # Write to file
            self._write_pruning_event(event)
            
            # Update statistics
            self.stats['total_pruning_events'] += 1
            self.stats['pruning_reasons'][cleanup_type] += 1
            
            logger.warning(f"🗑️ PRUNING EVENT: {symbol}")
            logger.warning(f"   Type: {cleanup_type}")
            logger.warning(f"   Reason: {reason}")
            logger.warning(f"   Final Score: {final_score:.0f}/100")
            logger.warning(f"   P&L: {final_pnl_pct*100:+.2f}%")
    
    def _write_score_record(self, record: PositionScoreRecord):
        """Write score record to JSONL file"""
        try:
            with open(self.score_records_file, 'a') as f:
                f.write(json.dumps(record.to_dict()) + '\n')
        except Exception as e:
            logger.error(f"Failed to write score record: {e}")
    
    def _write_pruning_event(self, event: PruningEvent):
        """Write pruning event to JSONL file"""
        try:
            with open(self.pruning_events_file, 'a') as f:
                f.write(json.dumps(event.to_dict()) + '\n')
        except Exception as e:
            logger.error(f"Failed to write pruning event: {e}")
    
    def get_position_history(self, symbol: str) -> List[PositionScoreRecord]:
        """Get score history for a specific position"""
        with self._lock:
            return self.score_history.get(symbol, [])
    
    def get_survival_stats(self) -> Dict:
        """
        Get statistics on position survival vs pruning
        
        Returns:
            Dictionary with survival statistics
        """
        with self._lock:
            total_scores = self.stats['total_scores_recorded']
            survival_count = self.stats['survival_count']
            
            return {
                'total_scores_recorded': total_scores,
                'positions_survived': survival_count,
                'positions_pruned': total_scores - survival_count,
                'survival_rate': survival_count / total_scores if total_scores > 0 else 0.0,
                'pruning_rate': (total_scores - survival_count) / total_scores if total_scores > 0 else 0.0,
                'pruning_breakdown': dict(self.stats['pruning_reasons'])
            }
    
    def get_score_distribution(self) -> Dict[str, int]:
        """
        Get distribution of scores
        
        Returns:
            Dictionary with score ranges and counts
        """
        with self._lock:
            distribution = {
                '0-20 (critical)': 0,
                '20-40 (poor)': 0,
                '40-60 (fair)': 0,
                '60-80 (good)': 0,
                '80-100 (excellent)': 0
            }
            
            for records in self.score_history.values():
                for record in records:
                    if record.score < 20:
                        distribution['0-20 (critical)'] += 1
                    elif record.score < 40:
                        distribution['20-40 (poor)'] += 1
                    elif record.score < 60:
                        distribution['40-60 (fair)'] += 1
                    elif record.score < 80:
                        distribution['60-80 (good)'] += 1
                    else:
                        distribution['80-100 (excellent)'] += 1
            
            return distribution
    
    def generate_telemetry_report(self) -> Dict:
        """
        Generate comprehensive telemetry report
        
        Returns:
            Dictionary with telemetry summary
        """
        with self._lock:
            report = {
                'timestamp': datetime.now().isoformat(),
                'overview': {
                    'positions_tracked': self.stats['positions_tracked'],
                    'total_scores_recorded': self.stats['total_scores_recorded'],
                    'total_pruning_events': self.stats['total_pruning_events']
                },
                'survival_stats': self.get_survival_stats(),
                'score_distribution': self.get_score_distribution(),
                'pruning_breakdown': dict(self.stats['pruning_reasons']),
                'recent_prunings': [
                    event.to_dict() 
                    for event in self.pruning_events[-10:]  # Last 10 pruning events
                ]
            }
            
            # Save to summary file
            try:
                with open(self.summary_file, 'w') as f:
                    json.dump(report, f, indent=2)
            except Exception as e:
                logger.error(f"Failed to save telemetry report: {e}")
            
            return report
    
    def print_summary(self):
        """Print telemetry summary to logs"""
        report = self.generate_telemetry_report()
        
        logger.info("\n" + "=" * 70)
        logger.info("POSITION SCORE TELEMETRY SUMMARY")
        logger.info("=" * 70)
        
        overview = report['overview']
        logger.info(f"Positions Tracked: {overview['positions_tracked']}")
        logger.info(f"Total Scores Recorded: {overview['total_scores_recorded']}")
        logger.info(f"Total Pruning Events: {overview['total_pruning_events']}")
        
        survival = report['survival_stats']
        logger.info(f"\nSurvival Rate: {survival['survival_rate']*100:.1f}%")
        logger.info(f"Pruning Rate: {survival['pruning_rate']*100:.1f}%")
        
        logger.info("\nScore Distribution:")
        for range_name, count in report['score_distribution'].items():
            logger.info(f"   {range_name}: {count}")
        
        logger.info("\nPruning Breakdown:")
        for reason, count in report['pruning_breakdown'].items():
            logger.info(f"   {reason}: {count}")
        
        logger.info("=" * 70 + "\n")


# Singleton instance
_default_telemetry = None


def get_position_telemetry(data_dir: str = "./data") -> PositionScoreTelemetry:
    """
    Get default position telemetry instance
    
    Args:
        data_dir: Data directory (used only on first call)
    
    Returns:
        PositionScoreTelemetry instance
    """
    global _default_telemetry
    
    if _default_telemetry is None:
        _default_telemetry = PositionScoreTelemetry(data_dir)
    
    return _default_telemetry


# Example usage
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    telemetry = PositionScoreTelemetry()
    
    # Simulate some score records
    telemetry.record_position_score(
        symbol="BTC-USD",
        score=85.0,
        pnl_pct=0.025,
        age_hours=2.0,
        stagnation_hours=0.5,
        pnl_contribution=30.0,
        stagnation_contribution=10.0,
        age_contribution=5.0,
        survived_pruning=True,
        health_status="excellent",
        size_usd=100.0
    )
    
    telemetry.record_position_score(
        symbol="ETH-USD",
        score=25.0,
        pnl_pct=-0.015,
        age_hours=12.0,
        stagnation_hours=8.0,
        pnl_contribution=-30.0,
        stagnation_contribution=-25.0,
        age_contribution=-15.0,
        survived_pruning=False,
        pruning_reason="Unhealthy position (score: 25, strong loss, stagnant 8.0h)",
        health_status="unhealthy",
        size_usd=50.0
    )
    
    # Record pruning event
    telemetry.record_pruning_event(
        symbol="ETH-USD",
        reason="Unhealthy position (score: 25, strong loss, stagnant 8.0h)",
        cleanup_type="UNHEALTHY",
        final_score=25.0,
        final_pnl_pct=-0.015,
        size_usd=50.0,
        age_hours=12.0
    )
    
    # Print summary
    telemetry.print_summary()
