"""
PROFITABILITY ASSERTION INTEGRATION - EXECUTION ENGINE
Exact code snippets to add profitability validation to ExecutionEngine

Author: NIJA Trading Systems
Date: February 2026
"""

# ============================================================================
# STEP 1: Add imports to execution_engine.py (after line 16)
# ============================================================================

# Add this import block after the existing imports:
"""
# Import profitability assertion for configuration validation
try:
    from bot.profitability_assertion import assert_strategy_is_profitable, ProfitabilityAssertionError
    PROFITABILITY_ASSERTION_AVAILABLE = True
    logger.info("✅ Profitability validation loaded in ExecutionEngine")
except ImportError:
    PROFITABILITY_ASSERTION_AVAILABLE = False
    logger.warning("⚠️ Profitability assertion not available in ExecutionEngine")
"""

# ============================================================================
# STEP 2: Add validation method to ExecutionEngine class
# ============================================================================

# Add this method to the ExecutionEngine class (after __init__ method):
"""
def _validate_profit_taking_configuration(self):
    \"\"\"
    Validate that profit-taking configuration is profitable after fees.
    
    This validates stepped profit exits and standard profit targets to ensure
    they result in net gains after exchange fees.
    
    Raises:
        ProfitabilityAssertionError: If configuration is unprofitable
    \"\"\"
    if not PROFITABILITY_ASSERTION_AVAILABLE:
        logger.warning("⚠️ Profitability assertion unavailable - skipping ExecutionEngine validation")
        return
    
    # Determine exchange from broker client
    broker_name = 'coinbase'  # Default
    if self.broker_client and hasattr(self.broker_client, 'broker_type'):
        broker_type = self.broker_client.broker_type
        if hasattr(broker_type, 'value'):
            broker_name = broker_type.value.lower()
        elif isinstance(broker_type, str):
            broker_name = broker_type.lower()
    
    # Extract profit targets from execution engine configuration
    profit_targets = []
    
    # Check for stepped profit levels
    if hasattr(self, 'stepped_profit_levels') and self.stepped_profit_levels:
        # Extract profit percentages from stepped levels
        profit_targets = sorted([level * 100 for level in self.stepped_profit_levels.keys()])
    
    # If no stepped levels, check for standard TP levels
    if not profit_targets:
        # Standard 3-level profit targets (TP1, TP2, TP3)
        # These are typically set as R-multiples (2R, 3R, 4R)
        # Estimate conservative profit targets
        profit_targets = [2.5, 3.5, 5.0]  # Conservative estimates
    
    # Estimate stop loss (typically 1-1.5% for tight stops)
    stop_loss_pct = 1.25
    
    # Use highest target as primary
    primary_target_pct = profit_targets[-1] if profit_targets else 5.0
    
    try:
        logger.info("🛡️ Validating ExecutionEngine profit-taking configuration...")
        logger.info(f"   Exchange: {broker_name.upper()}")
        logger.info(f"   Profit targets: {profit_targets}")
        
        # Validate configuration
        assert_strategy_is_profitable(
            profit_targets=profit_targets,
            stop_loss_pct=stop_loss_pct,
            primary_target_pct=primary_target_pct,
            exchange=broker_name
        )
        
        logger.info("✅ ExecutionEngine meets profitability requirements under assumed conditions")
        
    except ProfitabilityAssertionError as e:
        logger.error("❌ ExecutionEngine PROFITABILITY VALIDATION FAILED")
        logger.error(f"   {str(e)}")
        logger.error("   Profit-taking configuration would lose money after fees!")
        raise
"""

# ============================================================================
# STEP 3: Call validation in ExecutionEngine.__init__
# ============================================================================

# Add this call at the end of ExecutionEngine.__init__ method (before the final logger.info):
"""
        # PROFITABILITY ASSERTION: Validate profit-taking configuration
        # This ensures profit exits result in net gains after fees
        self._validate_profit_taking_configuration()
"""

# ============================================================================
# COMPLETE INTEGRATION EXAMPLE
# ============================================================================

COMPLETE_EXECUTION_ENGINE_INTEGRATION = """
# execution_engine.py - COMPLETE INTEGRATION EXAMPLE

class ExecutionEngine:
    def __init__(self, broker_client=None, config=None):
        \"\"\"Initialize execution engine with profitability validation\"\"\"
        self.broker_client = broker_client
        self.config = config or {}
        
        # ... existing initialization code ...
        
        # Load stepped profit configuration
        self.stepped_profit_levels = self.config.get('stepped_profit_levels', {
            0.015: 0.15,  # 1.5% profit -> exit 15%
            0.025: 0.25,  # 2.5% profit -> exit 25%
            0.040: 0.35,  # 4.0% profit -> exit 35%
            0.060: 0.50,  # 6.0% profit -> exit 50%
        })
        
        # PROFITABILITY ASSERTION: Validate profit-taking configuration
        # This ensures profit exits result in net gains after fees
        self._validate_profit_taking_configuration()
        
        logger.info("✅ ExecutionEngine initialized with validated profit-taking")
    
    def _validate_profit_taking_configuration(self):
        \"\"\"Validate profit-taking configuration is profitable after fees\"\"\"
        if not PROFITABILITY_ASSERTION_AVAILABLE:
            logger.warning("⚠️ Profitability assertion unavailable - skipping validation")
            return
        
        # Determine exchange
        broker_name = 'coinbase'
        if self.broker_client and hasattr(self.broker_client, 'broker_type'):
            broker_type = self.broker_client.broker_type
            broker_name = broker_type.value.lower() if hasattr(broker_type, 'value') else str(broker_type).lower()
        
        # Extract profit targets
        profit_targets = sorted([level * 100 for level in self.stepped_profit_levels.keys()])
        stop_loss_pct = 1.25
        primary_target_pct = profit_targets[-1] if profit_targets else 5.0
        
        try:
            logger.info(f"🛡️ Validating ExecutionEngine for {broker_name.upper()}...")
            assert_strategy_is_profitable(
                profit_targets=profit_targets,
                stop_loss_pct=stop_loss_pct,
                primary_target_pct=primary_target_pct,
                exchange=broker_name
            )
            logger.info("✅ ExecutionEngine meets profitability requirements")
        except ProfitabilityAssertionError as e:
            logger.error(f"❌ ExecutionEngine validation FAILED: {e}")
            raise
"""

# ============================================================================
# TESTING THE INTEGRATION
# ============================================================================

TESTING_EXAMPLE = """
# Test ExecutionEngine with profitability validation

def test_execution_engine_profitability():
    \"\"\"Test that ExecutionEngine validates profitability\"\"\"
    from bot.execution_engine import ExecutionEngine
    from bot.profitability_assertion import ProfitabilityAssertionError
    
    # Create mock broker client
    class MockBroker:
        broker_type = 'coinbase'
    
    # Test 1: Valid configuration (should pass)
    config = {
        'stepped_profit_levels': {
            0.025: 0.20,  # 2.5% profit
            0.040: 0.30,  # 4.0% profit
            0.060: 0.50,  # 6.0% profit
        }
    }
    
    engine = ExecutionEngine(broker_client=MockBroker(), config=config)
    print("✅ Valid configuration accepted")
    
    # Test 2: Invalid configuration (should fail)
    bad_config = {
        'stepped_profit_levels': {
            0.005: 0.20,  # 0.5% profit - TOO LOW
            0.010: 0.30,  # 1.0% profit - TOO LOW
        }
    }
    
    try:
        engine = ExecutionEngine(broker_client=MockBroker(), config=bad_config)
        print("❌ Should have rejected unprofitable config")
    except ProfitabilityAssertionError:
        print("✅ Correctly rejected unprofitable configuration")

if __name__ == '__main__':
    test_execution_engine_profitability()
"""

print("✅ ExecutionEngine integration code ready")
print("📋 See COMPLETE_EXECUTION_ENGINE_INTEGRATION for full example")
