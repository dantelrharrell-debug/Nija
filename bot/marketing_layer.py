"""
NIJA Marketing Layer

Public-facing reporting and marketing materials with appropriate disclaimers.
Generates investor-ready reports with proper risk disclosures.

Responsibilities:
- Generate public performance reports
- Create marketing-ready statistics
- Ensure all disclaimers are present
- Format data for external consumption
- Investor-grade reporting

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
    from institutional_disclaimers import (
        get_institutional_logger, 
        VALIDATION_DISCLAIMER,
        PERFORMANCE_DISCLAIMER,
        RISK_DISCLAIMER
    )
    from performance_tracking_layer import get_performance_tracking_layer
    from validation_layer import get_validation_layer
except ImportError:
    from bot.institutional_disclaimers import (
        get_institutional_logger,
        VALIDATION_DISCLAIMER,
        PERFORMANCE_DISCLAIMER,
        RISK_DISCLAIMER
    )
    from bot.performance_tracking_layer import get_performance_tracking_layer
    from bot.validation_layer import get_validation_layer

logger = get_institutional_logger(__name__)


class MarketingLayer:
    """
    Marketing Layer - Public-facing reporting with disclaimers
    
    All reports include appropriate disclaimers for institutional compliance.
    """
    
    def __init__(self, output_dir: str = "./data/reports"):
        """Initialize marketing layer"""
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        logger.info("✅ Marketing Layer initialized")
    
    def generate_performance_report(self, 
                                   include_validation: bool = True,
                                   include_live_stats: bool = True) -> Dict[str, Any]:
        """
        Generate comprehensive performance report with all disclaimers.
        
        Args:
            include_validation: Include validation layer results
            include_live_stats: Include live performance statistics
            
        Returns:
            Dictionary with complete report data
        """
        logger.info("📊 Generating institutional-grade performance report")
        
        report = {
            'report_date': datetime.now().isoformat(),
            'disclaimers': {
                'validation': VALIDATION_DISCLAIMER.strip(),
                'performance': PERFORMANCE_DISCLAIMER.strip(),
                'risk': RISK_DISCLAIMER.strip()
            }
        }
        
        # Add validation data
        if include_validation:
            validation_layer = get_validation_layer()
            report['validation'] = validation_layer.get_validation_summary()
        
        # Add live performance statistics
        if include_live_stats:
            performance_layer = get_performance_tracking_layer()
            stats = performance_layer.get_statistics_summary()
            
            report['live_performance'] = {
                'disclaimer': 'PAST PERFORMANCE DOES NOT GUARANTEE FUTURE RESULTS',
                **stats
            }
        
        return report
    
    def generate_statistical_report(self) -> Dict[str, Any]:
        """
        Generate statistical report with key metrics.
        
        Includes:
        - Win rate over last 100 trades
        - Max drawdown
        - Rolling expectancy
        - Equity curve
        
        Returns:
            Dictionary with statistical data
        """
        logger.info("📈 Generating statistical report")
        
        performance_layer = get_performance_tracking_layer()
        
        report = {
            'report_date': datetime.now().isoformat(),
            'report_type': 'Statistical Analysis',
            'disclaimers': {
                'primary': VALIDATION_DISCLAIMER.strip(),
                'performance': PERFORMANCE_DISCLAIMER.strip(),
                'risk': RISK_DISCLAIMER.strip()
            },
            'statistics': {
                'win_rate_last_100_trades': {
                    'value': performance_layer.get_win_rate_last_100(),
                    'unit': 'percentage',
                    'description': 'Win rate calculated over the last 100 trades'
                },
                'max_drawdown': {
                    'value': performance_layer.get_max_drawdown(),
                    'unit': 'percentage',
                    'description': 'Maximum peak-to-trough decline in account value'
                },
                'rolling_expectancy': {
                    'value': performance_layer.get_rolling_expectancy(),
                    'unit': 'currency',
                    'description': 'Expected value per trade over last 100 trades'
                },
                'equity_curve': {
                    'data_points': len(performance_layer.get_equity_curve()),
                    'description': 'Account value progression over time'
                }
            },
            'total_trades': len(performance_layer.all_trades),
            'data_quality': {
                'sample_size': len(performance_layer.all_trades),
                'sufficient_data': len(performance_layer.all_trades) >= 100,
                'note': 'Statistical significance improves with larger sample sizes'
            }
        }
        
        return report
    
    def export_investor_report(self, 
                              filename: Optional[str] = None,
                              format: str = 'json') -> str:
        """
        Export investor-ready performance report.
        
        Args:
            filename: Optional custom filename
            format: Report format ('json' or 'txt')
            
        Returns:
            Path to exported report
        """
        logger.info("📄 Exporting investor-ready report")
        
        if filename is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            extension = 'json' if format == 'json' else 'txt'
            filename = f"investor_report_{timestamp}.{extension}"
        
        filepath = self.output_dir / filename
        
        # Generate complete report
        report = self.generate_performance_report(
            include_validation=True,
            include_live_stats=True
        )
        
        # Add statistical report
        report['statistical_analysis'] = self.generate_statistical_report()['statistics']
        
        if format == 'json':
            with open(filepath, 'w') as f:
                json.dump(report, f, indent=2)
        else:
            # Plain text format
            with open(filepath, 'w') as f:
                f.write("=" * 80 + "\n")
                f.write("NIJA TRADING BOT - INVESTOR PERFORMANCE REPORT\n")
                f.write("=" * 80 + "\n\n")
                
                # Write disclaimers
                f.write(VALIDATION_DISCLAIMER + "\n")
                f.write(PERFORMANCE_DISCLAIMER + "\n")
                f.write(RISK_DISCLAIMER + "\n")
                f.write("=" * 80 + "\n\n")
                
                # Write statistics
                f.write("PERFORMANCE STATISTICS\n")
                f.write("-" * 80 + "\n")
                
                if 'live_performance' in report:
                    stats = report['live_performance']
                    f.write(f"Total Trades: {stats.get('total_trades', 0)}\n")
                    f.write(f"Win Rate (Last 100): {stats.get('win_rate_last_100', 0):.2f}%\n")
                    f.write(f"Max Drawdown: {stats.get('max_drawdown_pct', 0):.2f}%\n")
                    f.write(f"Rolling Expectancy: ${stats.get('rolling_expectancy', 0):.2f}\n")
                    f.write(f"Total Return: {stats.get('total_return_pct', 0):.2f}%\n")
                
                f.write("\n" + "=" * 80 + "\n")
                f.write(f"Report Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write("=" * 80 + "\n")
        
        logger.info(f"✅ Investor report exported to {filepath}")
        return str(filepath)
    
    def export_equity_curve_csv(self, filename: Optional[str] = None) -> str:
        """
        Export equity curve as CSV for charting.
        
        Args:
            filename: Optional custom filename
            
        Returns:
            Path to exported CSV
        """
        if filename is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"equity_curve_{timestamp}.csv"
        
        filepath = self.output_dir / filename
        
        performance_layer = get_performance_tracking_layer()
        equity_curve = performance_layer.get_equity_curve()
        
        with open(filepath, 'w') as f:
            f.write("timestamp,balance,trade_count\n")
            for point in equity_curve:
                f.write(f"{point['timestamp']},{point['balance']},{point['trade_count']}\n")
        
        logger.info(f"✅ Equity curve exported to {filepath}")
        return str(filepath)
    
    def get_summary_for_marketing(self) -> str:
        """
        Get a marketing-friendly summary with all disclaimers.
        
        Returns:
            Formatted summary string
        """
        performance_layer = get_performance_tracking_layer()
        stats = performance_layer.get_statistics_summary()
        
        summary = f"""
{VALIDATION_DISCLAIMER}

NIJA Trading Bot - Performance Summary
Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

KEY STATISTICS:
- Win Rate (Last 100 Trades): {stats.get('win_rate_last_100', 0):.2f}%
- Maximum Drawdown: {stats.get('max_drawdown_pct', 0):.2f}%
- Rolling Expectancy: ${stats.get('rolling_expectancy', 0):.2f} per trade
- Total Trades Executed: {stats.get('total_trades', 0)}
- Total Return: {stats.get('total_return_pct', 0):.2f}%

{PERFORMANCE_DISCLAIMER}

{RISK_DISCLAIMER}
"""
        return summary


# Global singleton
_marketing_layer: Optional[MarketingLayer] = None


def get_marketing_layer() -> MarketingLayer:
    """
    Get or create the global marketing layer instance.
    
    Returns:
        MarketingLayer instance
    """
    global _marketing_layer
    
    if _marketing_layer is None:
        _marketing_layer = MarketingLayer()
    
    return _marketing_layer


# Example usage
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    # Initialize marketing layer
    marketing = get_marketing_layer()
    
    # Generate and print summary
    summary = marketing.get_summary_for_marketing()
    print(summary)
    
    # Export reports
    json_report = marketing.export_investor_report(format='json')
    txt_report = marketing.export_investor_report(format='txt')
    csv_curve = marketing.export_equity_curve_csv()
    
    print(f"\nReports generated:")
    print(f"- JSON: {json_report}")
    print(f"- TXT: {txt_report}")
    print(f"- CSV: {csv_curve}")
