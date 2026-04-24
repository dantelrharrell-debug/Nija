# Entry Discipline Integration Guide

## Overview

This guide explains how to integrate the Institutional Entry Discipline framework into NIJA's trading system.

**Purpose:** Lock down entry criteria with hard rules (no discretionary overrides) after edge is proven.

## Integration Points

### 1. Trading Strategy Integration

The entry discipline gate should be added to `bot/trading_strategy.py` before broker execution.

#### Current Entry Flow

```python
# Current flow in trading_strategy.py
def _is_broker_eligible_for_entry(self, broker):
    """Check if broker can take new entries"""
    # Existing checks...
    return True, "Broker eligible"
```

#### Enhanced Flow with Entry Discipline

```python
from institutional_entry_discipline import (
    InstitutionalEntryDiscipline,
    SignalQuality,
    EntryDecision
)

class TradingStrategy:
    def __init__(self, ...):
        # Initialize entry discipline
        self.entry_discipline = InstitutionalEntryDiscipline()
    
    def _evaluate_entry_signal(self, symbol, current_data):
        """
        Evaluate entry signal before execution
        
        This gates ALL entries with institutional discipline
        """
        # Extract signal metrics from current_data
        signal_quality = SignalQuality(
            signal_strength=self._calculate_signal_strength(current_data),
            num_confirming_indicators=self._count_confirming_indicators(current_data),
            rsi_oversold=self._check_rsi_oversold(current_data),
            trend_aligned=self._check_trend_alignment(current_data),
            volume_confirmed=self._check_volume_confirmation(current_data),
            momentum_positive=self._check_momentum(current_data),
            risk_reward_ratio=self._calculate_risk_reward(current_data),
            stop_distance_pct=self._calculate_stop_distance(current_data),
            current_regime=self._detect_regime(current_data),
            volatility_pct=self._calculate_volatility(current_data),
            liquidity_usd=self._get_liquidity(symbol),
            spread_pct=self._get_current_spread(symbol),
            max_correlation=self._calculate_max_correlation(symbol),
            hours_since_news=self._hours_since_last_news(symbol)
        )
        
        # Evaluate against hard criteria
        evaluation = self.entry_discipline.evaluate_entry(symbol, signal_quality)
        
        if evaluation.decision != EntryDecision.APPROVED:
            logger.info(f"🚫 Entry rejected for {symbol}: {evaluation.decision.value}")
            for reason in evaluation.rejection_reasons:
                logger.info(f"   - {reason}")
            return False, evaluation.rejection_reasons[0] if evaluation.rejection_reasons else "Criteria not met"
        
        logger.info(f"✅ Entry approved for {symbol} (score: {evaluation.overall_score:.2%})")
        return True, "Entry criteria met"
```

### 2. Helper Methods to Implement

Add these helper methods to your TradingStrategy class:

```python
def _calculate_signal_strength(self, data) -> float:
    """
    Calculate overall signal strength (0-1)
    
    Combines multiple indicators into single strength score
    """
    rsi = self._get_rsi(data)
    macd = self._get_macd(data)
    volume = self._get_volume_indicator(data)
    
    # Example: Weighted combination
    strength = 0.0
    
    # RSI strength (stronger at extremes)
    if rsi < 30:
        strength += 0.4  # Strong oversold
    elif rsi < 40:
        strength += 0.2  # Mild oversold
    
    # MACD confirmation
    if macd > 0 and macd > macd_signal:
        strength += 0.3
    
    # Volume confirmation
    if volume > volume_avg * 1.2:
        strength += 0.3
    
    return min(strength, 1.0)

def _count_confirming_indicators(self, data) -> int:
    """Count how many indicators confirm the signal"""
    confirmations = 0
    
    if self._check_rsi_oversold(data):
        confirmations += 1
    if self._check_trend_alignment(data):
        confirmations += 1
    if self._check_volume_confirmation(data):
        confirmations += 1
    if self._check_momentum(data):
        confirmations += 1
    
    return confirmations

def _check_rsi_oversold(self, data) -> bool:
    """Check if RSI indicates oversold"""
    rsi = self._get_rsi(data)
    return rsi < 35

def _check_trend_alignment(self, data) -> bool:
    """Check if trade aligns with trend"""
    # Example: Price above 50-period MA = uptrend
    ma_50 = data['close'].rolling(50).mean().iloc[-1]
    current_price = data['close'].iloc[-1]
    return current_price > ma_50

def _check_volume_confirmation(self, data) -> bool:
    """Check if volume confirms move"""
    current_volume = data['volume'].iloc[-1]
    avg_volume = data['volume'].rolling(20).mean().iloc[-1]
    return current_volume > avg_volume * 1.3

def _check_momentum(self, data) -> bool:
    """Check if momentum supports entry"""
    # Example: Price making higher highs
    recent_high = data['high'].iloc[-5:].max()
    current_price = data['close'].iloc[-1]
    return current_price >= recent_high * 0.98

def _calculate_risk_reward(self, data) -> float:
    """Calculate risk/reward ratio for trade"""
    entry_price = data['close'].iloc[-1]
    stop_loss = self._calculate_stop_loss(data)
    take_profit = self._calculate_take_profit(data)
    
    risk = abs(entry_price - stop_loss)
    reward = abs(take_profit - entry_price)
    
    return reward / risk if risk > 0 else 0

def _calculate_stop_distance(self, data) -> float:
    """Calculate stop loss distance as percentage"""
    entry_price = data['close'].iloc[-1]
    stop_loss = self._calculate_stop_loss(data)
    
    return abs(entry_price - stop_loss) / entry_price

def _detect_regime(self, data) -> str:
    """
    Detect current market regime
    
    Returns: 'bull', 'bear', or 'sideways'
    """
    # Use existing market_regime_detector if available
    try:
        from market_regime_detector import MarketRegimeDetector
        detector = MarketRegimeDetector()
        return detector.detect_regime(data)
    except:
        # Fallback: Simple regime detection
        ma_50 = data['close'].rolling(50).mean().iloc[-1]
        ma_200 = data['close'].rolling(200).mean().iloc[-1]
        
        if ma_50 > ma_200 * 1.02:
            return 'bull'
        elif ma_50 < ma_200 * 0.98:
            return 'bear'
        else:
            return 'sideways'

def _calculate_volatility(self, data) -> float:
    """Calculate current volatility (ATR/price)"""
    try:
        from indicators import calculate_atr
        atr = calculate_atr(data['high'], data['low'], data['close'], period=14)
        return atr.iloc[-1] / data['close'].iloc[-1]
    except:
        # Fallback: Simple volatility
        returns = data['close'].pct_change()
        return returns.std()

def _get_liquidity(self, symbol) -> float:
    """Get daily volume in USD"""
    # This should fetch from exchange or cache
    # Example: Return recent 24h volume
    return 1000000.0  # Placeholder

def _get_current_spread(self, symbol) -> float:
    """Get current bid-ask spread as percentage"""
    # This should fetch from exchange order book
    # Example:
    # orderbook = self.broker.get_orderbook(symbol)
    # best_bid = orderbook['bids'][0][0]
    # best_ask = orderbook['asks'][0][0]
    # return (best_ask - best_bid) / best_bid
    return 0.001  # Placeholder (0.1%)

def _calculate_max_correlation(self, symbol) -> float:
    """Calculate max correlation with existing positions"""
    if not self.open_positions:
        return 0.0
    
    # Compare with each existing position
    max_corr = 0.0
    for pos in self.open_positions:
        if pos.symbol != symbol:
            corr = self._calculate_correlation(symbol, pos.symbol)
            max_corr = max(max_corr, abs(corr))
    
    return max_corr

def _calculate_correlation(self, symbol1, symbol2, periods=30) -> float:
    """Calculate correlation between two symbols"""
    # This should fetch historical data and calculate correlation
    # Placeholder implementation
    return 0.3

def _hours_since_last_news(self, symbol) -> float:
    """Calculate hours since last major news event"""
    # This should check news feed or calendar
    # Placeholder: Assume no recent news
    return 24.0
```

### 3. Integration with Existing Market Readiness Gate

You can use `institutional_entry_discipline` alongside the existing `market_readiness_gate`:

```python
from market_readiness_gate import MarketReadinessGate, MarketMode
from institutional_entry_discipline import InstitutionalEntryDiscipline

class TradingStrategy:
    def __init__(self, ...):
        # Layer 1: Market Readiness (global market conditions)
        self.market_readiness = MarketReadinessGate()
        
        # Layer 2: Entry Discipline (per-trade criteria)
        self.entry_discipline = InstitutionalEntryDiscipline()
    
    def should_take_entry(self, symbol, data):
        """
        Two-layer entry gating:
        1. Global market readiness
        2. Per-trade entry discipline
        """
        # Layer 1: Check market readiness
        market_mode = self.market_readiness.get_current_mode()
        if market_mode == MarketMode.IDLE:
            logger.info("🚫 Entry blocked: Market in IDLE mode")
            return False, "Market not ready"
        
        # Layer 2: Check entry discipline
        eligible, reason = self._evaluate_entry_signal(symbol, data)
        if not eligible:
            logger.info(f"🚫 Entry blocked: {reason}")
            return False, reason
        
        return True, "All criteria met"
```

### 4. Configuration

Create a configuration file `config/entry_discipline_config.py`:

```python
"""
Entry Discipline Configuration

Adjust these settings to control entry strictness.
"""

from bot.institutional_entry_discipline import HardEntryCriteria

# Conservative settings (stricter)
CONSERVATIVE_CRITERIA = HardEntryCriteria(
    min_signal_strength=0.75,           # 75% minimum
    min_confluence_indicators=3,        # Need 3 confirming indicators
    min_risk_reward_ratio=2.0,          # 2:1 R:R minimum
    max_stop_distance_pct=0.02,         # Max 2% stop
    min_volatility_pct=0.008,           # Min 0.8% volatility
    max_volatility_pct=0.04,            # Max 4% volatility
    min_liquidity_usd=200000,           # Min $200k volume
    max_spread_pct=0.0015,              # Max 0.15% spread
    min_hours_since_news=4.0,           # Wait 4 hours after news
    max_correlation_existing=0.60,      # Max 60% correlation
    allowed_regimes=['bull', 'sideways']  # Avoid bear markets
)

# Moderate settings (balanced)
MODERATE_CRITERIA = HardEntryCriteria(
    min_signal_strength=0.65,
    min_confluence_indicators=2,
    min_risk_reward_ratio=1.5,
    max_stop_distance_pct=0.03,
    min_volatility_pct=0.005,
    max_volatility_pct=0.05,
    min_liquidity_usd=100000,
    max_spread_pct=0.002,
    min_hours_since_news=2.0,
    max_correlation_existing=0.70,
    allowed_regimes=['bull', 'sideways']
)

# Aggressive settings (looser, for experienced operators only)
AGGRESSIVE_CRITERIA = HardEntryCriteria(
    min_signal_strength=0.55,
    min_confluence_indicators=2,
    min_risk_reward_ratio=1.2,
    max_stop_distance_pct=0.04,
    min_volatility_pct=0.003,
    max_volatility_pct=0.06,
    min_liquidity_usd=50000,
    max_spread_pct=0.0025,
    min_hours_since_news=1.0,
    max_correlation_existing=0.80,
    allowed_regimes=['bull', 'bear', 'sideways']  # Trade all regimes
)
```

Load in your strategy:

```python
from config.entry_discipline_config import MODERATE_CRITERIA

class TradingStrategy:
    def __init__(self, ...):
        # Use moderate criteria by default
        self.entry_discipline = InstitutionalEntryDiscipline(
            criteria=MODERATE_CRITERIA
        )
```

### 5. Monitoring and Statistics

Periodically log entry discipline statistics:

```python
# In your main trading loop or monitoring script
def log_entry_statistics():
    """Log entry discipline statistics"""
    strategy.entry_discipline.log_statistics()

# Call every hour or at end of day
scheduler.add_job(log_entry_statistics, 'interval', hours=1)
```

Example output:

```
============================================================
ENTRY DISCIPLINE STATISTICS
============================================================
Total Evaluations: 1,250
Approved: 187 (15.0%)
Rejected: 1,063

Rejection Breakdown:
  rejected_regime: 456 (42.9%)
  rejected_signal: 312 (29.3%)
  rejected_volatility: 187 (17.6%)
  rejected_liquidity: 108 (10.2%)
============================================================
```

### 6. Audit Trail

All entry decisions are automatically logged to disk for audit:

```
data/entry_discipline/
├── entry_eval_BTC-USD_20260218_140530.json
├── entry_eval_ETH-USD_20260218_140545.json
└── entry_eval_SOL-USD_20260218_140602.json
```

Each file contains:
- Decision (approved/rejected)
- All criteria evaluations
- Signal quality metrics
- Rejection reasons (if rejected)
- Timestamp

This provides a complete audit trail for:
- Performance analysis
- Regulatory compliance
- Strategy improvement

## Testing

### Unit Tests

Create `test_entry_discipline_integration.py`:

```python
import pytest
from trading_strategy import TradingStrategy
from institutional_entry_discipline import EntryDecision

def test_entry_discipline_rejects_low_signal():
    """Test that low signal strength is rejected"""
    strategy = TradingStrategy()
    
    # Create data with weak signal
    data = create_weak_signal_data()
    
    eligible, reason = strategy.should_take_entry('BTC-USD', data)
    
    assert not eligible
    assert 'signal strength' in reason.lower()

def test_entry_discipline_rejects_unfavorable_regime():
    """Test that bear market entries are rejected (if configured)"""
    strategy = TradingStrategy()
    
    # Create data in bear market
    data = create_bear_market_data()
    
    eligible, reason = strategy.should_take_entry('BTC-USD', data)
    
    assert not eligible
    assert 'regime' in reason.lower()

def test_entry_discipline_approves_good_signal():
    """Test that good signals are approved"""
    strategy = TradingStrategy()
    
    # Create data with strong signal
    data = create_strong_signal_data()
    
    eligible, reason = strategy.should_take_entry('BTC-USD', data)
    
    assert eligible
```

### Integration Tests

Test with historical data:

```python
def test_entry_discipline_with_historical_data():
    """Test entry discipline with real historical data"""
    strategy = TradingStrategy()
    
    # Load historical data
    data = load_historical_data('BTC-USD', days=30)
    
    approved_count = 0
    rejected_count = 0
    
    for i in range(len(data) - 50):
        window = data.iloc[i:i+50]
        eligible, reason = strategy.should_take_entry('BTC-USD', window)
        
        if eligible:
            approved_count += 1
        else:
            rejected_count += 1
    
    # Should have reasonable approval rate (10-30%)
    approval_rate = approved_count / (approved_count + rejected_count)
    assert 0.10 <= approval_rate <= 0.30
```

## Deployment Checklist

Before deploying entry discipline to production:

- [ ] Run `prove_edge.py` and confirm edge is proven
- [ ] Implement all helper methods in trading_strategy.py
- [ ] Add entry discipline to strategy initialization
- [ ] Configure criteria (conservative/moderate/aggressive)
- [ ] Test with historical data
- [ ] Verify audit trail is working
- [ ] Set up monitoring/statistics logging
- [ ] Document any custom criteria changes
- [ ] Dry-run for 24 hours before live deployment
- [ ] Review first 100 entry decisions manually

## Troubleshooting

### Issue: Too many rejections (>90%)

**Solution:** Criteria may be too strict. Consider:
- Lowering `min_signal_strength`
- Reducing `min_confluence_indicators`
- Expanding `allowed_regimes`

### Issue: Too many approvals (>40%)

**Solution:** Criteria may be too loose. Consider:
- Raising `min_signal_strength`
- Increasing `min_risk_reward_ratio`
- Tightening regime filters

### Issue: Performance degradation after integration

**Solution:**
- Review rejected entries - are good trades being blocked?
- Re-run `prove_edge.py` with entry discipline applied
- Adjust criteria based on backtesting results

## Next Steps

1. **Implement helper methods** in your TradingStrategy class
2. **Add entry discipline gate** before broker execution
3. **Configure criteria** based on your risk tolerance
4. **Test thoroughly** with historical data
5. **Deploy to dry-run** mode first
6. **Monitor statistics** and adjust as needed
7. **Document any customizations** for your team

Remember: **The goal is discipline, not restriction.** Entry discipline protects capital by ensuring only high-quality setups are traded.
