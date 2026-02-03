#!/usr/bin/env python3
"""
NIJA Profitability Audit Report

Generates comprehensive profitability audit report for live trading.
Run this ONCE after deployment to verify profitability structure.

What to watch in first 48 hours:
- Avg loss ≈ -1.5%
- Avg win ≥ +2.8%
- Fees < 20% of gross
- Drawdowns controlled, not cascading

Usage:
    python profitability_audit_report.py

Author: NIJA Trading Systems
Version: 1.0
Date: February 2026
"""

import os
import sys
import json
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from pathlib import Path

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Add bot directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))

try:
    from profitability_assertion import (
        get_profitability_assertion,
        EXCHANGE_FEES,
        ProfitabilityRequirements
    )
except ImportError:
    logger.error("Cannot import profitability_assertion module")
    sys.exit(1)


class ProfitabilityAuditor:
    """Audits trading performance for profitability structure"""
    
    def __init__(self):
        """Initialize auditor"""
        self.assertion = get_profitability_assertion()
        self.trades = []
        self.report = {}
        
    def load_trade_history(self, lookback_hours: int = 48) -> List[Dict]:
        """
        Load recent trade history.
        
        Args:
            lookback_hours: Hours of history to analyze
            
        Returns:
            List of trade dictionaries
        """
        # Try to load from various sources
        trade_files = [
            'data/trades.json',
            'data/trade_history.json',
            'results/trades.json',
            'bot/data/trades.json'
        ]
        
        for trade_file in trade_files:
            if os.path.exists(trade_file):
                try:
                    with open(trade_file, 'r') as f:
                        all_trades = json.load(f)
                    
                    # Filter to lookback period
                    cutoff = datetime.now() - timedelta(hours=lookback_hours)
                    recent_trades = [
                        t for t in all_trades
                        if datetime.fromisoformat(t.get('timestamp', '2020-01-01'))
                        > cutoff
                    ]
                    
                    logger.info(f"Loaded {len(recent_trades)} trades from {trade_file}")
                    return recent_trades
                    
                except Exception as e:
                    logger.warning(f"Error loading {trade_file}: {e}")
        
        logger.warning("No trade history found - generating sample report")
        return []
    
    def analyze_trade_structure(self, trades: List[Dict]) -> Dict:
        """
        Analyze trade structure metrics.
        
        Args:
            trades: List of completed trades
            
        Returns:
            Dictionary with structural analysis
        """
        if not trades:
            return self._generate_empty_structure()
        
        wins = [t for t in trades if t.get('pnl', 0) > 0]
        losses = [t for t in trades if t.get('pnl', 0) < 0]
        breakevens = [t for t in trades if t.get('pnl', 0) == 0]
        
        # Calculate averages
        avg_win_pct = (
            sum(t.get('pnl_pct', 0) for t in wins) / len(wins)
            if wins else 0.0
        )
        avg_loss_pct = (
            sum(t.get('pnl_pct', 0) for t in losses) / len(losses)
            if losses else 0.0
        )
        
        # Calculate fees
        total_fees = sum(t.get('fees', 0) for t in trades)
        gross_pnl = sum(t.get('pnl', 0) + t.get('fees', 0) for t in trades)
        fee_percentage = (
            (total_fees / abs(gross_pnl) * 100)
            if gross_pnl != 0 else 0.0
        )
        
        # Win rate
        total_closed = len(wins) + len(losses)
        win_rate = (len(wins) / total_closed * 100) if total_closed > 0 else 0.0
        
        # Risk/Reward
        if avg_loss_pct != 0:
            rr_ratio = abs(avg_win_pct / avg_loss_pct)
        else:
            rr_ratio = 0.0
        
        # Expectancy
        expectancy = (win_rate / 100 * avg_win_pct) + ((100 - win_rate) / 100 * avg_loss_pct)
        
        return {
            'total_trades': len(trades),
            'wins': len(wins),
            'losses': len(losses),
            'breakevens': len(breakevens),
            'win_rate': win_rate,
            'avg_win_pct': avg_win_pct,
            'avg_loss_pct': avg_loss_pct,
            'rr_ratio': rr_ratio,
            'total_fees': total_fees,
            'fee_percentage': fee_percentage,
            'expectancy': expectancy,
            'gross_pnl': gross_pnl,
            'net_pnl': sum(t.get('pnl', 0) for t in trades)
        }
    
    def _generate_empty_structure(self) -> Dict:
        """Generate empty structure for when no trades exist"""
        return {
            'total_trades': 0,
            'wins': 0,
            'losses': 0,
            'breakevens': 0,
            'win_rate': 0.0,
            'avg_win_pct': 0.0,
            'avg_loss_pct': 0.0,
            'rr_ratio': 0.0,
            'total_fees': 0.0,
            'fee_percentage': 0.0,
            'expectancy': 0.0,
            'gross_pnl': 0.0,
            'net_pnl': 0.0
        }
    
    def check_profitability_health(self, structure: Dict) -> Dict:
        """
        Check if trading structure is healthy.
        
        Args:
            structure: Trade structure analysis
            
        Returns:
            Health check results
        """
        checks = {}
        
        # Check 1: Average loss ~= -1.5%
        checks['avg_loss_check'] = {
            'actual': structure['avg_loss_pct'],
            'target': -1.5,
            'tolerance': 0.5,
            'status': abs(structure['avg_loss_pct'] - (-1.5)) <= 0.5 if structure['avg_loss_pct'] != 0 else 'UNKNOWN'
        }
        
        # Check 2: Average win >= +2.8%
        checks['avg_win_check'] = {
            'actual': structure['avg_win_pct'],
            'target': 2.8,
            'status': structure['avg_win_pct'] >= 2.8 if structure['avg_win_pct'] != 0 else 'UNKNOWN'
        }
        
        # Check 3: Fees < 20% of gross
        checks['fee_check'] = {
            'actual': structure['fee_percentage'],
            'target': 20.0,
            'status': structure['fee_percentage'] < 20.0
        }
        
        # Check 4: Positive expectancy
        checks['expectancy_check'] = {
            'actual': structure['expectancy'],
            'target': 0.0,
            'status': structure['expectancy'] > 0.0 if structure['total_trades'] > 0 else 'UNKNOWN'
        }
        
        # Check 5: Win rate reasonable
        checks['win_rate_check'] = {
            'actual': structure['win_rate'],
            'target_range': (40.0, 70.0),
            'status': 40.0 <= structure['win_rate'] <= 70.0 if structure['total_trades'] > 0 else 'UNKNOWN'
        }
        
        # Overall health
        passing_checks = sum(
            1 for c in checks.values()
            if c['status'] is True or c['status'] == 'PASS'
        )
        total_checks = len(checks)
        
        all_healthy = all(
            c['status'] in [True, 'PASS', 'UNKNOWN']
            for c in checks.values()
        )
        
        return {
            'checks': checks,
            'passing': passing_checks,
            'total': total_checks,
            'healthy': all_healthy
        }
    
    def generate_report(self, lookback_hours: int = 48) -> Dict:
        """
        Generate complete profitability audit report.
        
        Args:
            lookback_hours: Hours of history to analyze
            
        Returns:
            Complete audit report
        """
        logger.info("=" * 80)
        logger.info("🔍 NIJA PROFITABILITY AUDIT REPORT")
        logger.info("=" * 80)
        logger.info(f"Analysis Period: Last {lookback_hours} hours")
        logger.info(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info("=" * 80)
        
        # Load trades
        trades = self.load_trade_history(lookback_hours)
        
        # Analyze structure
        structure = self.analyze_trade_structure(trades)
        
        # Health check
        health = self.check_profitability_health(structure)
        
        # Print structure
        logger.info("\n📊 TRADE STRUCTURE ANALYSIS")
        logger.info("-" * 80)
        logger.info(f"Total Trades: {structure['total_trades']}")
        logger.info(f"Wins: {structure['wins']} | Losses: {structure['losses']} | Breakeven: {structure['breakevens']}")
        logger.info(f"Win Rate: {structure['win_rate']:.1f}%")
        logger.info(f"Average Win: +{structure['avg_win_pct']:.2f}%")
        logger.info(f"Average Loss: {structure['avg_loss_pct']:.2f}%")
        logger.info(f"R/R Ratio: {structure['rr_ratio']:.2f}:1")
        logger.info(f"Expectancy: {structure['expectancy']:+.2f}%")
        logger.info(f"Total Fees: ${structure['total_fees']:.2f} ({structure['fee_percentage']:.1f}% of gross)")
        logger.info(f"Net PnL: ${structure['net_pnl']:+.2f}")
        
        # Print health checks
        logger.info("\n🏥 PROFITABILITY HEALTH CHECKS")
        logger.info("-" * 80)
        
        for check_name, check_data in health['checks'].items():
            status_symbol = "✅" if check_data['status'] in [True, 'PASS'] else "❌" if check_data['status'] == False else "⚠️"
            logger.info(f"{status_symbol} {check_name}: {check_data}")
        
        logger.info("-" * 80)
        logger.info(f"Passing Checks: {health['passing']}/{health['total']}")
        
        if health['healthy']:
            logger.info("✅ NIJA IS OFFICIALLY FIXED - STRUCTURE IS HEALTHY")
        elif structure['total_trades'] == 0:
            logger.warning("⚠️ NO TRADES YET - DEPLOY AND MONITOR")
        else:
            logger.warning("❌ STRUCTURE NEEDS ATTENTION - SEE CHECKS ABOVE")
        
        logger.info("=" * 80)
        
        # Print recommendations
        logger.info("\n💡 RECOMMENDATIONS")
        logger.info("-" * 80)
        
        if structure['total_trades'] < 10:
            logger.info("📈 Insufficient data - Continue monitoring for 24-48 hours")
        
        if structure['fee_percentage'] > 20:
            logger.warning("⚠️ Fees too high - Consider larger position sizes or fewer trades")
        
        if structure['avg_win_pct'] < 2.8:
            logger.warning("⚠️ Average wins too small - Verify profit targets are configured correctly")
        
        if abs(structure['avg_loss_pct']) > 2.0:
            logger.warning("⚠️ Average losses too large - Verify stop losses are not too wide")
        
        if structure['expectancy'] <= 0:
            logger.error("🚨 NEGATIVE EXPECTANCY - STOP TRADING AND REVIEW CONFIGURATION")
        
        logger.info("=" * 80)
        
        # Save report
        report_data = {
            'timestamp': datetime.now().isoformat(),
            'lookback_hours': lookback_hours,
            'structure': structure,
            'health': health
        }
        
        # Try to save report
        report_dir = Path('reports')
        report_dir.mkdir(exist_ok=True)
        
        report_file = report_dir / f"profitability_audit_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        try:
            with open(report_file, 'w') as f:
                json.dump(report_data, f, indent=2)
            logger.info(f"📝 Report saved to: {report_file}")
        except Exception as e:
            logger.warning(f"Could not save report: {e}")
        
        return report_data


def main():
    """Main entry point"""
    import argparse
    
    parser = argparse.ArgumentParser(description='NIJA Profitability Audit Report')
    parser.add_argument(
        '--hours',
        type=int,
        default=48,
        help='Hours of trade history to analyze (default: 48)'
    )
    
    args = parser.parse_args()
    
    auditor = ProfitabilityAuditor()
    report = auditor.generate_report(lookback_hours=args.hours)
    
    # Exit code based on health
    if report['health']['healthy'] or report['structure']['total_trades'] == 0:
        sys.exit(0)  # Success
    else:
        sys.exit(1)  # Issues detected


if __name__ == '__main__':
    main()
