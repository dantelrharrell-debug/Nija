"""
MMIN Integration Example
=========================

Example showing how to integrate MMIN with NIJA's existing trading system
"""

import os
import sys
import logging
from datetime import datetime

# Add bot directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))

from mmin import MMINEngine

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)


def basic_mmin_usage():
    """Basic MMIN usage example"""
    print("\n" + "="*80)
    print("BASIC MMIN USAGE")
    print("="*80)

    # Initialize MMIN
    mmin = MMINEngine()

    # Check status
    status = mmin.get_status()
    print(f"\n✓ MMIN Status:")
    print(f"  - Enabled: {status['enabled']}")
    print(f"  - Mode: {status['mode']}")
    print(f"  - Intelligence Level: {status['intelligence_level']}")
    print(f"  - Current Regime: {status['current_regime']}")

    # Run market analysis
    print(f"\n✓ Running market analysis...")
    analysis = mmin.analyze_markets(timeframe='1h', limit=200)

    if analysis.get('status') != 'no_data':
        print(f"\n✓ Analysis Results:")
        print(f"  - Markets Analyzed: {analysis['markets_analyzed']}")
        print(f"  - Macro Regime: {analysis['macro_regime']['regime'].value}")
        print(f"  - Regime Confidence: {analysis['macro_regime']['confidence']:.1%}")
        print(f"  - Signals Generated: {len(analysis['signals'])}")

        # Show capital allocation
        if 'capital_allocation' in analysis:
            alloc = analysis['capital_allocation']
            print(f"\n✓ Capital Allocation ({alloc['strategy']}):")
            total = alloc['total_capital']
            for market, capital in sorted(alloc['allocations'].items(),
                                         key=lambda x: x[1], reverse=True):
                pct = (capital / total) * 100
                print(f"    {market:12s}: ${capital:>10,.0f} ({pct:>5.1f}%)")


def advanced_signal_filtering():
    """Example: Use MMIN for advanced signal filtering"""
    print("\n" + "="*80)
    print("ADVANCED SIGNAL FILTERING WITH MMIN")
    print("="*80)

    mmin = MMINEngine()

    # Run analysis
    analysis = mmin.analyze_markets(timeframe='1h', limit=200)

    if analysis.get('status') == 'no_data':
        print("No data available")
        return

    regime = analysis['macro_regime']
    signals = analysis['signals']

    print(f"\n✓ Macro Regime: {regime['regime'].value}")
    print(f"✓ Trading Implications:")
    implications = regime['trading_implications']
    print(f"  - Preferred Markets: {', '.join(implications['preferred_markets'])}")
    print(f"  - Position Sizing: {implications['position_sizing']}")
    print(f"  - Strategy Focus: {implications['strategy_focus']}")

    # Filter signals based on regime
    preferred_markets = implications['preferred_markets']
    filtered_signals = [
        s for s in signals
        if s['market_type'] in preferred_markets and s['confidence'] >= 0.7
    ]

    print(f"\n✓ Signals: {len(signals)} total, {len(filtered_signals)} after regime filtering")

    if filtered_signals:
        print(f"\n✓ High-Confidence Signals (regime-aligned):")
        for i, signal in enumerate(filtered_signals[:5], 1):
            print(f"  {i}. {signal['symbol']} ({signal['market_type']}):")
            print(f"     Direction: {signal['signal_type'].upper()}")
            print(f"     Confidence: {signal['confidence']:.1%}")
            print(f"     Cross-Market Confirmations: {signal.get('cross_market_confirmations', 0)}")


def correlation_based_trading():
    """Example: Use correlations for signal confirmation"""
    print("\n" + "="*80)
    print("CORRELATION-BASED SIGNAL CONFIRMATION")
    print("="*80)

    mmin = MMINEngine()

    # Run analysis
    analysis = mmin.analyze_markets(timeframe='1h', limit=200)

    if analysis.get('status') == 'no_data':
        print("No data available")
        return

    correlations = analysis.get('correlations', {})

    if correlations and 'significant_pairs' in correlations:
        print(f"\n✓ Significant Correlations Found:")
        for sym1, sym2, corr in correlations['significant_pairs'][:10]:
            corr_type = "Positive" if corr > 0 else "Negative"
            print(f"  {sym1:15s} ↔ {sym2:15s}: {corr:>6.3f} ({corr_type})")

        # Diversification opportunities
        if 'diversification_opportunities' in correlations:
            print(f"\n✓ Diversification Opportunities:")
            for opp in correlations['diversification_opportunities']:
                print(f"  {opp}")

    # Cross-market confirmation logic
    signals = analysis.get('signals', [])
    confirmed_signals = [
        s for s in signals
        if s.get('cross_market_confirmations', 0) >= 2
    ]

    print(f"\n✓ Signals with Cross-Market Confirmation:")
    print(f"  Total Signals: {len(signals)}")
    print(f"  Confirmed (2+ markets): {len(confirmed_signals)}")


def capital_allocation_strategy():
    """Example: Dynamic capital allocation across markets"""
    print("\n" + "="*80)
    print("DYNAMIC CAPITAL ALLOCATION")
    print("="*80)

    from mmin import GlobalCapitalRouter

    router = GlobalCapitalRouter()

    # Simulate market performance metrics
    market_metrics = {
        'crypto': {
            'sharpe_ratio': 2.3,
            'win_rate': 0.64,
            'profit_factor': 2.5,
            'opportunity_count': 12,
        },
        'equities': {
            'sharpe_ratio': 1.9,
            'win_rate': 0.59,
            'profit_factor': 2.1,
            'opportunity_count': 18,
        },
        'forex': {
            'sharpe_ratio': 1.6,
            'win_rate': 0.55,
            'profit_factor': 1.8,
            'opportunity_count': 8,
        },
        'commodities': {
            'sharpe_ratio': 1.4,
            'win_rate': 0.52,
            'profit_factor': 1.6,
            'opportunity_count': 5,
        },
    }

    # Calculate allocation
    total_capital = 250000.0
    allocation = router.calculate_allocation(
        market_metrics,
        macro_regime='growth',
        total_capital=total_capital
    )

    print(f"\n✓ Allocation Strategy: {router.strategy}")
    print(f"✓ Total Capital: ${total_capital:,.0f}")
    print(f"\n✓ Market Allocation:")

    for market, capital in sorted(allocation.items(), key=lambda x: x[1], reverse=True):
        pct = (capital / total_capital) * 100
        metrics = market_metrics[market]
        print(f"\n  {market.upper()}:")
        print(f"    Capital: ${capital:>10,.0f} ({pct:>5.1f}%)")
        print(f"    Sharpe: {metrics['sharpe_ratio']:.2f}")
        print(f"    Win Rate: {metrics['win_rate']:.1%}")
        print(f"    Profit Factor: {metrics['profit_factor']:.2f}")
        print(f"    Opportunities: {metrics['opportunity_count']}")


def transfer_learning_example():
    """Example: Transfer learning across markets"""
    print("\n" + "="*80)
    print("TRANSFER LEARNING ACROSS MARKETS")
    print("="*80)

    from mmin import TransferLearningEngine, MultiMarketDataCollector

    collector = MultiMarketDataCollector()
    transfer = TransferLearningEngine()

    # Learn pattern from crypto
    crypto_data = list(collector.collect_market_data('crypto', limit=100).values())
    if crypto_data:
        crypto_df = crypto_data[0]

        # Simulate learning from successful trade
        outcome = {'profit': 0.035, 'win': True, 'trade_duration': 12}
        pattern = transfer.learn_pattern(crypto_df, 'crypto', 'breakout', outcome)

        print(f"\n✓ Pattern Learned from Crypto:")
        print(f"  Type: {pattern.pattern_type}")
        print(f"  Confidence: {pattern.confidence:.1%}")
        print(f"  Features: {len(pattern.features)} dimensions")

    # Find similar patterns in equities
    equity_data = list(collector.collect_market_data('equities', limit=100).values())
    if equity_data:
        equity_df = equity_data[0]
        similar = transfer.find_similar_patterns(equity_df, 'equities',
                                                 pattern_types=['breakout'],
                                                 min_confidence=0.5)

        print(f"\n✓ Similar Patterns Found in Equities:")
        print(f"  Count: {len(similar)}")

        if similar:
            best_match, similarity = similar[0]
            print(f"  Best Match Similarity: {similarity:.1%}")

            # Get transfer recommendation
            recommendation = transfer.transfer_pattern(best_match, 'equities')
            print(f"\n✓ Transfer Recommendation:")
            print(f"  Original Confidence: {recommendation['original_confidence']:.1%}")
            print(f"  Adjusted Confidence: {recommendation['adjusted_confidence']:.1%}")
            print(f"  Recommended: {'YES' if recommendation['recommended'] else 'NO'}")

    # Stats
    stats = transfer.get_learning_stats()
    print(f"\n✓ Transfer Learning Stats:")
    print(f"  Total Patterns Learned: {stats['total_patterns']}")
    print(f"  Transfer Routes: {stats['transfer_routes']}")


def main():
    """Run all examples"""
    print("\n" + "="*80)
    print("NIJA MMIN INTEGRATION EXAMPLES")
    print("="*80)
    print("\nThese examples show how to integrate MMIN into your trading system")

    try:
        # Run examples
        basic_mmin_usage()
        advanced_signal_filtering()
        correlation_based_trading()
        capital_allocation_strategy()
        transfer_learning_example()

        print("\n" + "="*80)
        print("✅ ALL EXAMPLES COMPLETED SUCCESSFULLY")
        print("="*80)
        print("\nNext Steps:")
        print("1. Review MMIN_DOCUMENTATION.md for detailed API reference")
        print("2. Customize mmin_config.py for your trading preferences")
        print("3. Integrate MMIN signals into your existing strategy")
        print("4. Start with conservative allocation and increase gradually")
        print("\n🚀 MMIN is ready for integration!")
        print("="*80 + "\n")

    except Exception as e:
        print(f"\n❌ Example failed: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
