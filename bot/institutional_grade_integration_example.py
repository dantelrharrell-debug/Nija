"""
NIJA Institutional-Grade Integration Example

Demonstrates how to use the three-layer architecture:
- Validation Layer
- Performance Tracking Layer  
- Marketing Layer

Plus the Statistical Reporting Module.

Author: NIJA Trading Systems
Version: 1.0
Date: February 2026
"""

import logging
from datetime import datetime

# Import all layers
from bot.institutional_disclaimers import print_validation_banner
from bot.validation_layer import get_validation_layer
from bot.performance_tracking_layer import get_performance_tracking_layer
from bot.marketing_layer import get_marketing_layer
from bot.statistical_reporting_module import get_statistical_reporting_module

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)


def example_validation_workflow():
    """Example: Using the Validation Layer for strategy testing"""
    print("\n" + "=" * 80)
    print("EXAMPLE 1: VALIDATION LAYER WORKFLOW")
    print("=" * 80 + "\n")
    
    # Get validation layer
    validation = get_validation_layer()
    
    # Simulate some historical trades for validation
    historical_trades = [
        {'profit': 50, 'fees': 1},
        {'profit': -25, 'fees': 1},
        {'profit': 75, 'fees': 1.5},
        {'profit': 100, 'fees': 2},
        {'profit': -30, 'fees': 1},
        {'profit': 60, 'fees': 1.5},
        {'profit': -20, 'fees': 1},
        {'profit': 80, 'fees': 1.5},
    ]
    
    # Validate the strategy
    result = validation.validate_strategy(
        strategy_name="APEX_V71",
        historical_trades=historical_trades,
        validation_period_days=30
    )
    
    print(f"\nValidation Result:")
    print(f"  Strategy: {result.strategy_name}")
    print(f"  Win Rate: {result.win_rate:.2f}%")
    print(f"  Profit Factor: {result.profit_factor:.2f}")
    print(f"  Sample Size: {result.sample_size} trades")
    print(f"  Statistical Confidence: {result.statistical_confidence:.1f}%")
    
    # Get validation summary
    summary = validation.get_validation_summary()
    print(f"\nTotal Validations Performed: {summary['total_validations']}")


def example_performance_tracking_workflow():
    """Example: Using the Performance Tracking Layer for live trading"""
    print("\n" + "=" * 80)
    print("EXAMPLE 2: PERFORMANCE TRACKING LAYER WORKFLOW")
    print("=" * 80 + "\n")
    
    # Get performance tracking layer
    performance = get_performance_tracking_layer()
    
    # Set initial balance
    performance.set_initial_balance(10000.0)
    
    # Record some live trades
    trades = [
        ('BTC-USD', 'APEX_V71', 'buy', 45000, 46000, 0.1, 100, 2),
        ('ETH-USD', 'DUAL_RSI', 'buy', 3000, 2950, 1.0, -50, 1.5),
        ('SOL-USD', 'APEX_V71', 'buy', 120, 125, 10, 50, 1),
        ('BTC-USD', 'APEX_V71', 'buy', 46000, 47000, 0.1, 100, 2),
    ]
    
    for symbol, strategy, side, entry, exit, qty, profit, fees in trades:
        performance.record_trade(
            symbol=symbol,
            strategy=strategy,
            side=side,
            entry_price=entry,
            exit_price=exit,
            quantity=qty,
            profit=profit,
            fees=fees
        )
    
    # Get statistics
    stats = performance.get_statistics_summary()
    
    print(f"\nPerformance Statistics:")
    print(f"  Total Trades: {stats['total_trades']}")
    print(f"  Win Rate (Last 100): {stats['win_rate_last_100']:.2f}%")
    print(f"  Max Drawdown: {stats['max_drawdown_pct']:.2f}%")
    print(f"  Rolling Expectancy: ${stats['rolling_expectancy']:.2f}")
    print(f"  Current Balance: ${stats['current_balance']:,.2f}")
    print(f"  Total Return: {stats['total_return_pct']:.2f}%")


def example_marketing_layer_workflow():
    """Example: Using the Marketing Layer for reporting"""
    print("\n" + "=" * 80)
    print("EXAMPLE 3: MARKETING LAYER WORKFLOW")
    print("=" * 80 + "\n")
    
    # Get marketing layer
    marketing = get_marketing_layer()
    
    # Generate marketing summary
    summary = marketing.get_summary_for_marketing()
    print(summary)
    
    # Export investor reports
    print("\nExporting investor reports...")
    json_report = marketing.export_investor_report(format='json')
    txt_report = marketing.export_investor_report(format='txt')
    csv_curve = marketing.export_equity_curve_csv()
    
    print(f"  JSON Report: {json_report}")
    print(f"  Text Report: {txt_report}")
    print(f"  Equity Curve CSV: {csv_curve}")


def example_statistical_reporting_workflow():
    """Example: Using the Statistical Reporting Module"""
    print("\n" + "=" * 80)
    print("EXAMPLE 4: STATISTICAL REPORTING MODULE WORKFLOW")
    print("=" * 80 + "\n")
    
    # Get statistical reporting module
    stats_module = get_statistical_reporting_module()
    
    # Print summary to console
    stats_module.print_summary()
    
    # Generate comprehensive report
    report = stats_module.generate_comprehensive_report()
    
    print("\nComprehensive Report Generated:")
    print(f"  Report Type: {report['report_metadata']['report_type']}")
    print(f"  Generated At: {report['report_metadata']['generated_at']}")
    print(f"  Disclaimers Shown: {report['disclaimers']['displayed']}")
    
    # Export all reports
    print("\nExporting all reports...")
    exports = stats_module.export_all_reports()
    
    print("\nExported Files:")
    for name, path in exports.items():
        print(f"  {name}: {path}")


def main():
    """Run all examples"""
    print("\n" + "╔" + "=" * 78 + "╗")
    print("║" + " " * 15 + "NIJA INSTITUTIONAL-GRADE INTEGRATION EXAMPLES" + " " * 18 + "║")
    print("╚" + "=" * 78 + "╝")
    
    # Display validation banner
    print_validation_banner()
    
    # Run all examples
    example_validation_workflow()
    example_performance_tracking_workflow()
    example_marketing_layer_workflow()
    example_statistical_reporting_workflow()
    
    print("\n" + "=" * 80)
    print("✅ ALL EXAMPLES COMPLETED")
    print("=" * 80 + "\n")
    
    print("Next Steps:")
    print("1. Integrate layers into your trading bot's main loop")
    print("2. Call performance_layer.record_trade() after each trade execution")
    print("3. Use validation_layer.validate_strategy() for backtesting")
    print("4. Generate reports periodically using marketing_layer")
    print("5. Use statistical_reporting_module for comprehensive analysis")
    print()


if __name__ == "__main__":
    main()
