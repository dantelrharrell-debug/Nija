"""
NIJA Statistical Reporting Module

Comprehensive statistical reporting for institutional-grade analysis.

Features:
- Win rate over last 100 trades
- Max drawdown calculation
- Rolling expectancy
- Equity curve generation
- Statistical significance testing
- Institutional disclaimers

Author: NIJA Trading Systems
Version: 1.0
Date: February 2026
"""

import logging
from typing import Dict, List, Optional, Any
from datetime import datetime
from pathlib import Path
import json

try:
    from institutional_disclaimers import get_institutional_logger, print_validation_banner
    from performance_tracking_layer import get_performance_tracking_layer
    from validation_layer import get_validation_layer
    from marketing_layer import get_marketing_layer
except ImportError:
    from bot.institutional_disclaimers import get_institutional_logger, print_validation_banner
    from bot.performance_tracking_layer import get_performance_tracking_layer
    from bot.validation_layer import get_validation_layer
    from bot.marketing_layer import get_marketing_layer

logger = get_institutional_logger(__name__)


class StatisticalReportingModule:
    """
    Statistical reporting module for institutional-grade analysis.
    
    Integrates all three layers:
    - Validation Layer (mathematical validation)
    - Performance Tracking Layer (live results)
    - Marketing Layer (public reporting)
    """
    
    def __init__(self):
        """Initialize statistical reporting module"""
        # Display validation banner
        print_validation_banner()
        logger.show_validation_disclaimer()
        
        # Initialize layers
        self.validation_layer = get_validation_layer()
        self.performance_layer = get_performance_tracking_layer()
        self.marketing_layer = get_marketing_layer()
        
        logger.info("✅ Statistical Reporting Module initialized")
    
    def generate_comprehensive_report(self) -> Dict[str, Any]:
        """
        Generate comprehensive statistical report covering all layers.
        
        Returns:
            Dictionary with complete statistical analysis
        """
        logger.info("📊 Generating comprehensive statistical report")
        logger.show_validation_disclaimer()
        
        report = {
            'report_metadata': {
                'generated_at': datetime.now().isoformat(),
                'report_type': 'Comprehensive Statistical Analysis',
                'version': '1.0'
            },
            'disclaimers': {
                'displayed': True,
                'validation_disclaimer_shown': True,
                'performance_disclaimer_shown': True,
                'risk_disclaimer_shown': True
            },
            'key_statistics': self._get_key_statistics(),
            'validation_results': self.validation_layer.get_validation_summary(),
            'live_performance': self.performance_layer.get_statistics_summary(),
            'analysis': self._generate_analysis()
        }
        
        return report
    
    def _get_key_statistics(self) -> Dict[str, Any]:
        """
        Get the four key statistics for institutional reporting.
        
        Returns:
            Dictionary with key statistics
        """
        return {
            'win_rate_last_100_trades': {
                'value': self.performance_layer.get_win_rate_last_100(),
                'unit': 'percentage',
                'sample_size': min(len(self.performance_layer.recent_trades), 100),
                'description': 'Win rate over the most recent 100 trades',
                'statistical_note': 'Based on live trading results'
            },
            'max_drawdown': {
                'value': self.performance_layer.get_max_drawdown(),
                'unit': 'percentage',
                'description': 'Maximum peak-to-trough decline',
                'risk_metric': True,
                'interpretation': 'Lower is better - indicates downside risk'
            },
            'rolling_expectancy': {
                'value': self.performance_layer.get_rolling_expectancy(),
                'unit': 'currency',
                'description': 'Expected profit per trade (last 100 trades)',
                'formula': '(Win Rate × Avg Win) - (Loss Rate × Avg Loss)',
                'interpretation': 'Positive expectancy indicates edge'
            },
            'equity_curve': {
                'total_points': len(self.performance_layer.get_equity_curve()),
                'description': 'Account value progression over time',
                'data_available': len(self.performance_layer.get_equity_curve()) > 0,
                'export_format': 'CSV available via marketing layer'
            }
        }
    
    def _generate_analysis(self) -> Dict[str, Any]:
        """
        Generate analytical insights from statistics.
        
        Returns:
            Dictionary with analysis and insights
        """
        stats = self.performance_layer.get_statistics_summary()
        
        # Assess data quality
        total_trades = stats.get('total_trades', 0)
        data_quality = 'insufficient'
        if total_trades >= 100:
            data_quality = 'good'
        elif total_trades >= 30:
            data_quality = 'moderate'
        
        # Assess performance quality
        win_rate = stats.get('win_rate_last_100', 0)
        expectancy = stats.get('rolling_expectancy', 0)
        
        performance_quality = 'underperforming'
        if win_rate > 60 and expectancy > 0:
            performance_quality = 'strong'
        elif win_rate > 50 and expectancy > 0:
            performance_quality = 'adequate'
        
        # Risk assessment
        max_dd = stats.get('max_drawdown_pct', 0)
        risk_level = 'low'
        if max_dd > 20:
            risk_level = 'high'
        elif max_dd > 10:
            risk_level = 'moderate'
        
        return {
            'data_quality': {
                'assessment': data_quality,
                'total_trades': total_trades,
                'recommendation': 'Collect more data for statistical significance' if total_trades < 100 else 'Sample size adequate'
            },
            'performance_quality': {
                'assessment': performance_quality,
                'win_rate': win_rate,
                'expectancy': expectancy,
                'note': 'Based on recent trading history'
            },
            'risk_assessment': {
                'level': risk_level,
                'max_drawdown': max_dd,
                'recommendation': 'Review position sizing' if risk_level == 'high' else 'Risk levels acceptable'
            },
            'disclaimer': 'Analysis is for informational purposes only. Past performance does not guarantee future results.'
        }
    
    def print_summary(self):
        """Print a formatted summary to console"""
        print("\n" + "=" * 80)
        print("NIJA STATISTICAL REPORTING MODULE")
        print("=" * 80 + "\n")
        
        print_validation_banner()
        
        stats = self._get_key_statistics()
        
        print("\nKEY STATISTICS:")
        print("-" * 80)
        print(f"Win Rate (Last 100 Trades): {stats['win_rate_last_100_trades']['value']:.2f}%")
        print(f"  Sample Size: {stats['win_rate_last_100_trades']['sample_size']} trades")
        print()
        print(f"Maximum Drawdown: {stats['max_drawdown']['value']:.2f}%")
        print(f"  Interpretation: {stats['max_drawdown']['interpretation']}")
        print()
        print(f"Rolling Expectancy: ${stats['rolling_expectancy']['value']:.2f}")
        print(f"  Formula: {stats['rolling_expectancy']['formula']}")
        print()
        print(f"Equity Curve Data Points: {stats['equity_curve']['total_points']}")
        print(f"  Export: {stats['equity_curve']['export_format']}")
        
        print("\n" + "=" * 80)
        print("Report Generated:", datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
        print("=" * 80 + "\n")
    
    def export_all_reports(self, output_dir: Optional[str] = None) -> Dict[str, str]:
        """
        Export all reports in multiple formats.
        
        Args:
            output_dir: Optional custom output directory
            
        Returns:
            Dictionary with paths to all exported files
        """
        logger.info("📦 Exporting all reports")
        
        if output_dir:
            self.marketing_layer.output_dir = Path(output_dir)
            self.marketing_layer.output_dir.mkdir(parents=True, exist_ok=True)
        
        exports = {}
        
        # Export comprehensive JSON report
        comprehensive_report = self.generate_comprehensive_report()
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        json_path = self.marketing_layer.output_dir / f"comprehensive_report_{timestamp}.json"
        with open(json_path, 'w') as f:
            json.dump(comprehensive_report, f, indent=2)
        exports['comprehensive_json'] = str(json_path)
        
        # Export investor reports
        exports['investor_json'] = self.marketing_layer.export_investor_report(format='json')
        exports['investor_txt'] = self.marketing_layer.export_investor_report(format='txt')
        
        # Export equity curve
        exports['equity_curve_csv'] = self.marketing_layer.export_equity_curve_csv()
        
        # Export performance data
        exports['performance_stats'] = self.performance_layer.export_statistics()
        
        logger.info(f"✅ Exported {len(exports)} report files")
        
        return exports


# Global singleton
_statistical_reporting: Optional[StatisticalReportingModule] = None


def get_statistical_reporting_module() -> StatisticalReportingModule:
    """
    Get or create the global statistical reporting module instance.
    
    Returns:
        StatisticalReportingModule instance
    """
    global _statistical_reporting
    
    if _statistical_reporting is None:
        _statistical_reporting = StatisticalReportingModule()
    
    return _statistical_reporting


# CLI interface
if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='NIJA Statistical Reporting Module')
    parser.add_argument('--export', action='store_true', help='Export all reports')
    parser.add_argument('--output-dir', type=str, help='Output directory for exports')
    parser.add_argument('--summary', action='store_true', help='Print summary to console')
    
    args = parser.parse_args()
    
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    
    # Initialize module
    module = get_statistical_reporting_module()
    
    # Print summary if requested
    if args.summary or (not args.export):
        module.print_summary()
    
    # Export reports if requested
    if args.export:
        exports = module.export_all_reports(output_dir=args.output_dir)
        print("\nExported Reports:")
        for name, path in exports.items():
            print(f"  {name}: {path}")
