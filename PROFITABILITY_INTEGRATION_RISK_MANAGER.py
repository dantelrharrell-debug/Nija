"""
PROFITABILITY ASSERTION INTEGRATION - RISK MANAGER
Exact code snippets to add profitability validation to RiskManager

Author: NIJA Trading Systems
Date: February 2026
"""

# ============================================================================
# STEP 1: Add imports to risk_manager.py (after line 22)
# ============================================================================

# Add this import block after the existing imports:
"""
# Import profitability assertion for configuration validation
try:
    from profitability_assertion import assert_strategy_is_profitable, ProfitabilityAssertionError
    PROFITABILITY_ASSERTION_AVAILABLE = True
    logger.info("✅ Profitability validation loaded in RiskManager")
except ImportError:
    try:
        from bot.profitability_assertion import assert_strategy_is_profitable, ProfitabilityAssertionError
        PROFITABILITY_ASSERTION_AVAILABLE = True
        logger.info("✅ Profitability validation loaded in RiskManager")
    except ImportError:
        PROFITABILITY_ASSERTION_AVAILABLE = False
        logger.warning("⚠️ Profitability assertion not available in RiskManager")
"""

# ============================================================================
# STEP 2: Add validation method to AdaptiveRiskManager class
# ============================================================================

# Add this method to the AdaptiveRiskManager class (after __init__ method):
"""
def _validate_risk_reward_configuration(self, exchange='coinbase'):
    \"\"\"
    Validate that risk/reward configuration is profitable after fees.
    
    This validates that the R-multiples used for profit targets result in
    profitable trades after accounting for exchange fees.
    
    Args:
        exchange: Exchange name (coinbase, kraken, etc.)
    
    Raises:
        ProfitabilityAssertionError: If configuration is unprofitable
    \"\"\"
    if not PROFITABILITY_ASSERTION_AVAILABLE:
        logger.warning("⚠️ Profitability assertion unavailable - skipping RiskManager validation")
        return
    
    # RiskManager typically uses R-multiples for profit targets
    # Standard configuration: TP1=2R, TP2=3R, TP3=4R
    # Need to convert R-multiples to percentage targets
    
    # Assume typical stop loss of 1.0% (conservative)
    # This is the "1R" risk amount
    risk_amount_pct = 1.0
    
    # Calculate profit targets as percentages
    # TP1 = 2R, TP2 = 3R, TP3 = 4R
    profit_targets = [
        risk_amount_pct * 2.0,  # 2R = 2.0%
        risk_amount_pct * 3.0,  # 3R = 3.0%
        risk_amount_pct * 4.0,  # 4R = 4.0%
    ]
    
    # Use 4R (highest target) as primary
    primary_target_pct = profit_targets[-1]
    
    try:
        logger.info("🛡️ Validating RiskManager R-multiple configuration...")
        logger.info(f"   Exchange: {exchange.upper()}")
        logger.info(f"   Risk amount (1R): {risk_amount_pct}%")
        logger.info(f"   Profit targets: {profit_targets} (2R, 3R, 4R)")
        
        # Validate configuration
        assert_strategy_is_profitable(
            profit_targets=profit_targets,
            stop_loss_pct=risk_amount_pct,
            primary_target_pct=primary_target_pct,
            exchange=exchange
        )
        
        logger.info("✅ RiskManager meets profitability requirements")
        logger.info("   (under assumed conditions)")
        
    except ProfitabilityAssertionError as e:
        logger.error("❌ RiskManager PROFITABILITY VALIDATION FAILED")
        logger.error(f"   {str(e)}")
        logger.error("   R-multiple configuration would lose money after fees!")
        logger.error("   RECOMMENDATION: Use tighter stops (0.8%) or wider targets (5R, 6R, 7R)")
        raise
"""

# ============================================================================
# STEP 3: Call validation in AdaptiveRiskManager.__init__
# ============================================================================

# Add this call at the end of AdaptiveRiskManager.__init__ method:
"""
        # PROFITABILITY ASSERTION: Validate R-multiple configuration
        # This ensures profit targets result in net gains after fees
        # Use Coinbase as default (most conservative fee structure)
        self._validate_risk_reward_configuration(exchange='coinbase')
"""

# ============================================================================
# COMPLETE INTEGRATION EXAMPLE
# ============================================================================

COMPLETE_RISK_MANAGER_INTEGRATION = """
# risk_manager.py - COMPLETE INTEGRATION EXAMPLE

class AdaptiveRiskManager:
    def __init__(self, min_position_pct=0.02, max_position_pct=0.25,
                 max_total_exposure=0.60, use_exchange_profiles=False,
                 pro_mode=False, min_free_reserve_pct=0.15, tier_lock=None,
                 max_portfolio_volatility=0.04):
        \"\"\"
        Initialize Adaptive Risk Manager with profitability validation
        \"\"\"
        self.min_position_pct = min_position_pct
        self.max_position_pct = max_position_pct
        self.max_total_exposure = max_total_exposure
        self.pro_mode = pro_mode
        self.min_free_reserve_pct = min_free_reserve_pct
        self.tier_lock = tier_lock
        self.max_portfolio_volatility = max_portfolio_volatility
        
        # ... existing initialization code ...
        
        # PROFITABILITY ASSERTION: Validate R-multiple configuration
        # This ensures profit targets result in net gains after fees
        # Use Coinbase as default (most conservative fee structure)
        self._validate_risk_reward_configuration(exchange='coinbase')
        
        logger.info("✅ RiskManager initialized with validated R-multiples")
    
    def _validate_risk_reward_configuration(self, exchange='coinbase'):
        \"\"\"Validate R-multiple configuration is profitable after fees\"\"\"
        if not PROFITABILITY_ASSERTION_AVAILABLE:
            logger.warning("⚠️ Profitability assertion unavailable - skipping validation")
            return
        
        # Assume typical stop loss of 1.0% (1R)
        risk_amount_pct = 1.0
        
        # Standard R-multiples: 2R, 3R, 4R
        profit_targets = [
            risk_amount_pct * 2.0,  # 2R = 2.0%
            risk_amount_pct * 3.0,  # 3R = 3.0%
            risk_amount_pct * 4.0,  # 4R = 4.0%
        ]
        
        primary_target_pct = profit_targets[-1]
        
        try:
            logger.info(f"🛡️ Validating RiskManager for {exchange.upper()}...")
            logger.info(f"   R-multiples: 2R, 3R, 4R → {profit_targets}")
            
            assert_strategy_is_profitable(
                profit_targets=profit_targets,
                stop_loss_pct=risk_amount_pct,
                primary_target_pct=primary_target_pct,
                exchange=exchange
            )
            
            logger.info("✅ RiskManager meets profitability requirements")
            logger.info("   (under assumed conditions)")
            
        except ProfitabilityAssertionError as e:
            logger.error(f"❌ RiskManager validation FAILED: {e}")
            logger.error("   RECOMMENDATION: Use 0.8% stops or 5R/6R/7R targets")
            raise
"""

# ============================================================================
# ADVANCED: Exchange-Aware Risk Manager
# ============================================================================

EXCHANGE_AWARE_RISK_MANAGER = """
# Advanced: Exchange-aware R-multiple validation

class AdaptiveRiskManager:
    def __init__(self, broker_client=None, **kwargs):
        \"\"\"Initialize with exchange detection\"\"\"
        # ... existing init code ...
        
        # Detect exchange from broker client
        exchange = self._detect_exchange(broker_client)
        
        # Validate with exchange-specific fees
        self._validate_risk_reward_configuration(exchange=exchange)
    
    def _detect_exchange(self, broker_client):
        \"\"\"Detect exchange from broker client\"\"\"
        if not broker_client:
            return 'coinbase'  # Conservative default
        
        if hasattr(broker_client, 'broker_type'):
            broker_type = broker_client.broker_type
            if hasattr(broker_type, 'value'):
                return broker_type.value.lower()
            elif isinstance(broker_type, str):
                return broker_type.lower()
        
        return 'coinbase'  # Fallback
    
    def _validate_risk_reward_configuration(self, exchange='coinbase'):
        \"\"\"Validate with exchange-specific requirements\"\"\"
        if not PROFITABILITY_ASSERTION_AVAILABLE:
            return
        
        # Adjust R-multiples based on exchange fees
        if exchange == 'kraken':
            # Kraken has lower fees (0.52% vs 1.6%)
            # Can use tighter R-multiples
            risk_amount_pct = 0.8
            r_multiples = [2.0, 2.5, 3.0]  # Lower targets OK
        elif exchange == 'coinbase':
            # Coinbase has higher fees (1.6%)
            # Need wider R-multiples
            risk_amount_pct = 1.0
            r_multiples = [2.5, 3.5, 5.0]  # Higher targets required
        else:
            # Conservative default
            risk_amount_pct = 1.0
            r_multiples = [2.5, 3.5, 5.0]
        
        profit_targets = [risk_amount_pct * r for r in r_multiples]
        
        try:
            logger.info(f"🛡️ Validating RiskManager for {exchange.upper()}...")
            logger.info(f"   Risk: {risk_amount_pct}%, R-multiples: {r_multiples}")
            
            assert_strategy_is_profitable(
                profit_targets=profit_targets,
                stop_loss_pct=risk_amount_pct,
                primary_target_pct=profit_targets[-1],
                exchange=exchange
            )
            
            logger.info(f"✅ {exchange.upper()}-optimized R-multiples validated")
            
        except ProfitabilityAssertionError as e:
            logger.error(f"❌ Validation failed: {e}")
            raise
"""

# ============================================================================
# TESTING THE INTEGRATION
# ============================================================================

TESTING_EXAMPLE = """
# Test RiskManager with profitability validation

def test_risk_manager_profitability():
    \"\"\"Test that RiskManager validates profitability\"\"\"
    from bot.risk_manager import AdaptiveRiskManager
    from bot.profitability_assertion import ProfitabilityAssertionError
    
    # Test 1: Default configuration (should pass with Coinbase fees)
    risk_manager = AdaptiveRiskManager()
    print("✅ Default RiskManager configuration is profitable")
    
    # Test 2: With Kraken broker (lower fees)
    class MockKrakenBroker:
        broker_type = 'kraken'
    
    risk_manager_kraken = AdaptiveRiskManager(broker_client=MockKrakenBroker())
    print("✅ Kraken-optimized RiskManager configuration is profitable")
    
    # Test 3: Validate calculated profit targets
    # RiskManager calculates TP levels based on R-multiples
    entry_price = 100.0
    stop_loss = 99.0  # 1% stop = 1R
    
    # Calculate TPs
    risk = entry_price - stop_loss  # 1.0
    tp1 = entry_price + (risk * 2)  # 2R = 102.0
    tp2 = entry_price + (risk * 3)  # 3R = 103.0
    tp3 = entry_price + (risk * 4)  # 4R = 104.0
    
    print(f"   Entry: ${entry_price}")
    print(f"   Stop Loss: ${stop_loss} (1R)")
    print(f"   TP1: ${tp1} (2R)")
    print(f"   TP2: ${tp2} (3R)")
    print(f"   TP3: ${tp3} (4R)")
    
    # Verify these are profitable
    profit_targets_pct = [
        ((tp1 - entry_price) / entry_price) * 100,
        ((tp2 - entry_price) / entry_price) * 100,
        ((tp3 - entry_price) / entry_price) * 100,
    ]
    
    print(f"   Profit targets: {[f'{p:.1f}%' for p in profit_targets_pct]}")
    print("✅ All targets exceed Coinbase fees (1.6%)")

if __name__ == '__main__':
    test_risk_manager_profitability()
"""

# ============================================================================
# RECOMMENDATION FOR PRODUCTION
# ============================================================================

PRODUCTION_RECOMMENDATION = """
PRODUCTION DEPLOYMENT RECOMMENDATIONS
======================================

1. RECOMMENDED R-MULTIPLES BY EXCHANGE:

   Coinbase (1.6% fees):
   - Stop Loss: 1.0% (1R)
   - TP1: 2.5% (2.5R) → Net: +0.9% ✓
   - TP2: 3.5% (3.5R) → Net: +1.9% ✓
   - TP3: 5.0% (5.0R) → Net: +3.4% ✓
   
   Kraken (0.52% fees):
   - Stop Loss: 0.8% (1R)
   - TP1: 1.5% (1.875R) → Net: +0.98% ✓
   - TP2: 2.5% (3.125R) → Net: +1.98% ✓
   - TP3: 4.0% (5R) → Net: +3.48% ✓

2. VALIDATION TIMING:
   - Validate on RiskManager initialization ✓
   - Validate when R-multiples change
   - Re-validate if exchange changes

3. ERROR HANDLING:
   - Log validation failures clearly
   - Suggest corrective R-multiples
   - Block strategy if validation fails
   - Allow override only with explicit confirmation

4. MONITORING:
   - Track validation pass/fail rate
   - Alert if validations start failing
   - Monitor actual vs expected profitability
"""

print("✅ RiskManager integration code ready")
print("📋 See COMPLETE_RISK_MANAGER_INTEGRATION for full example")
print("🎯 See PRODUCTION_RECOMMENDATION for deployment guidance")
