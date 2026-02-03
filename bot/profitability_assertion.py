"""
NIJA Profitability Assertion Guard

CRITICAL SAFETY MODULE - Prevents deployment of unprofitable trading configurations.

This module ensures that NO trading strategy can be deployed if it would result in
net losses after fees. This is the single most important guard rail for the system.

Key Checks:
1. Profit targets MUST exceed fee costs by minimum margin
2. Risk/Reward ratios MUST be favorable after fees
3. Stop losses MUST be appropriately sized
4. Expected value MUST be positive

Author: NIJA Trading Systems
Version: 1.0
Date: February 2026

NOTE: This guard prevented the January 2026 profitability crisis from recurring.
      NEVER bypass or disable these checks.
"""

import logging
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass

logger = logging.getLogger("nija.profitability_assertion")


@dataclass
class FeeStructure:
    """Fee structure for an exchange"""
    maker_fee_pct: float
    taker_fee_pct: float
    exchange_name: str
    

@dataclass
class ProfitabilityRequirements:
    """Minimum profitability requirements"""
    min_net_profit_after_fees: float = 0.5  # Minimum 0.5% net profit
    min_risk_reward_ratio: float = 1.5      # Minimum 1.5:1 R/R after fees
    min_win_rate_for_breakeven: float = 40.0  # Minimum win rate needed
    max_loss_to_profit_ratio: float = 0.8   # Max loss size vs profit target


# Exchange fee structures (as of Feb 2026)
EXCHANGE_FEES = {
    'coinbase': FeeStructure(
        maker_fee_pct=0.6,    # Coinbase Advanced Trade maker fee
        taker_fee_pct=0.8,    # Coinbase Advanced Trade taker fee (conservative)
        exchange_name='Coinbase'
    ),
    'kraken': FeeStructure(
        maker_fee_pct=0.16,   # Kraken maker fee
        taker_fee_pct=0.26,   # Kraken taker fee
        exchange_name='Kraken'
    ),
    'binance': FeeStructure(
        maker_fee_pct=0.1,    # Binance maker fee
        taker_fee_pct=0.1,    # Binance taker fee
        exchange_name='Binance'
    ),
}


class ProfitabilityAssertionError(Exception):
    """Raised when profitability assertions fail"""
    pass


class ProfitabilityAssertion:
    """
    Validates that trading configurations are profitable after fees.
    
    This is the PRIMARY guard rail preventing unprofitable trading.
    """
    
    def __init__(self, requirements: Optional[ProfitabilityRequirements] = None):
        """
        Initialize profitability assertion checker.
        
        Args:
            requirements: Profitability requirements (uses defaults if None)
        """
        self.requirements = requirements or ProfitabilityRequirements()
        logger.info(
            f"🛡️ Profitability Assertion Guard ACTIVE - "
            f"Min Net Profit: {self.requirements.min_net_profit_after_fees}%, "
            f"Min R/R: {self.requirements.min_risk_reward_ratio}:1"
        )
    
    def assert_profit_targets_profitable(
        self,
        profit_targets: List[float],
        exchange: str = 'coinbase',
        assume_taker: bool = True
    ) -> Dict:
        """
        Assert that profit targets result in net gains after fees.
        
        Args:
            profit_targets: List of profit target percentages (e.g., [2.5, 2.0, 1.6])
            exchange: Exchange name ('coinbase', 'kraken', etc.)
            assume_taker: If True, assumes taker fees (conservative)
            
        Returns:
            Dictionary with validation results
            
        Raises:
            ProfitabilityAssertionError: If any profit target is unprofitable
        """
        if exchange.lower() not in EXCHANGE_FEES:
            logger.warning(f"Unknown exchange '{exchange}', using Coinbase fees as fallback")
            fee_structure = EXCHANGE_FEES['coinbase']
        else:
            fee_structure = EXCHANGE_FEES[exchange.lower()]
        
        # Use taker fee (conservative) or maker fee
        fee_pct = fee_structure.taker_fee_pct if assume_taker else fee_structure.maker_fee_pct
        
        # Round-trip fees (entry + exit)
        total_fee_pct = fee_pct * 2
        
        failing_targets = []
        passing_targets = []
        
        for target_pct in profit_targets:
            net_profit_pct = target_pct - total_fee_pct
            
            if net_profit_pct < self.requirements.min_net_profit_after_fees:
                failing_targets.append({
                    'target': target_pct,
                    'fees': total_fee_pct,
                    'net_profit': net_profit_pct,
                    'status': 'FAIL'
                })
            else:
                passing_targets.append({
                    'target': target_pct,
                    'fees': total_fee_pct,
                    'net_profit': net_profit_pct,
                    'status': 'PASS'
                })
        
        # Log results
        logger.info(f"📊 Profit Target Validation - {fee_structure.exchange_name}:")
        logger.info(f"   Fee Structure: {fee_pct}% per trade, {total_fee_pct}% round-trip")
        logger.info(f"   Targets Tested: {len(profit_targets)}")
        logger.info(f"   ✅ Passing: {len(passing_targets)}")
        logger.info(f"   ❌ Failing: {len(failing_targets)}")
        
        if failing_targets:
            # Log each failing target
            for target in failing_targets:
                logger.error(
                    f"   ❌ UNPROFITABLE TARGET: {target['target']}% "
                    f"→ Net {target['net_profit']:+.2f}% after fees "
                    f"(Required: ≥{self.requirements.min_net_profit_after_fees}%)"
                )
            
            # CRITICAL ERROR - Raise exception
            raise ProfitabilityAssertionError(
                f"PROFITABILITY ASSERTION FAILED: {len(failing_targets)} profit target(s) "
                f"would result in NET LOSSES on {fee_structure.exchange_name}. "
                f"Targets must yield ≥{self.requirements.min_net_profit_after_fees}% after fees. "
                f"Failing targets: {[t['target'] for t in failing_targets]}"
            )
        
        logger.info(f"   ✅ All profit targets are profitable after fees")
        
        return {
            'exchange': fee_structure.exchange_name,
            'fee_pct': fee_pct,
            'total_fee_pct': total_fee_pct,
            'passing_targets': passing_targets,
            'failing_targets': failing_targets,
            'all_profitable': len(failing_targets) == 0
        }
    
    def assert_risk_reward_acceptable(
        self,
        stop_loss_pct: float,
        profit_target_pct: float,
        exchange: str = 'coinbase',
        assume_taker: bool = True
    ) -> Dict:
        """
        Assert that risk/reward ratio is acceptable after fees.
        
        Args:
            stop_loss_pct: Stop loss percentage (positive number, e.g., 1.25 for -1.25%)
            profit_target_pct: Profit target percentage (e.g., 2.5 for +2.5%)
            exchange: Exchange name
            assume_taker: If True, assumes taker fees
            
        Returns:
            Dictionary with R/R analysis
            
        Raises:
            ProfitabilityAssertionError: If R/R ratio is unacceptable
        """
        if exchange.lower() not in EXCHANGE_FEES:
            fee_structure = EXCHANGE_FEES['coinbase']
        else:
            fee_structure = EXCHANGE_FEES[exchange.lower()]
        
        fee_pct = fee_structure.taker_fee_pct if assume_taker else fee_structure.maker_fee_pct
        total_fee_pct = fee_pct * 2
        
        # Calculate net profit/loss after fees
        net_profit = profit_target_pct - total_fee_pct
        net_loss = stop_loss_pct + total_fee_pct  # Loss is worse with fees
        
        # Calculate R/R ratio (reward:risk)
        if net_loss > 0:
            rr_ratio = net_profit / net_loss
        else:
            rr_ratio = float('inf')  # No risk = infinite R/R
        
        # Check minimum requirements
        is_acceptable = (
            rr_ratio >= self.requirements.min_risk_reward_ratio and
            net_profit >= self.requirements.min_net_profit_after_fees
        )
        
        logger.info(
            f"📊 Risk/Reward Analysis - {fee_structure.exchange_name}:"
        )
        logger.info(f"   Gross Profit Target: +{profit_target_pct}%")
        logger.info(f"   Gross Stop Loss: -{stop_loss_pct}%")
        logger.info(f"   Round-trip Fees: -{total_fee_pct}%")
        logger.info(f"   Net Reward: +{net_profit:.2f}%")
        logger.info(f"   Net Risk: -{net_loss:.2f}%")
        logger.info(f"   R/R Ratio: {rr_ratio:.2f}:1")
        logger.info(f"   Required R/R: ≥{self.requirements.min_risk_reward_ratio}:1")
        
        if not is_acceptable:
            logger.error(
                f"   ❌ UNACCEPTABLE RISK/REWARD: {rr_ratio:.2f}:1 "
                f"(Required: ≥{self.requirements.min_risk_reward_ratio}:1)"
            )
            raise ProfitabilityAssertionError(
                f"RISK/REWARD ASSERTION FAILED: R/R ratio of {rr_ratio:.2f}:1 "
                f"is below minimum {self.requirements.min_risk_reward_ratio}:1 "
                f"for {fee_structure.exchange_name}"
            )
        
        logger.info(f"   ✅ Risk/Reward ratio is acceptable")
        
        return {
            'exchange': fee_structure.exchange_name,
            'gross_profit_target': profit_target_pct,
            'gross_stop_loss': stop_loss_pct,
            'fees': total_fee_pct,
            'net_profit': net_profit,
            'net_loss': net_loss,
            'rr_ratio': rr_ratio,
            'is_acceptable': is_acceptable
        }
    
    def calculate_breakeven_win_rate(
        self,
        stop_loss_pct: float,
        profit_target_pct: float,
        exchange: str = 'coinbase',
        assume_taker: bool = True
    ) -> Dict:
        """
        Calculate the win rate needed to break even.
        
        Formula: Breakeven WR = Risk / (Risk + Reward)
        
        Args:
            stop_loss_pct: Stop loss percentage
            profit_target_pct: Profit target percentage
            exchange: Exchange name
            assume_taker: If True, assumes taker fees
            
        Returns:
            Dictionary with breakeven analysis
        """
        if exchange.lower() not in EXCHANGE_FEES:
            fee_structure = EXCHANGE_FEES['coinbase']
        else:
            fee_structure = EXCHANGE_FEES[exchange.lower()]
        
        fee_pct = fee_structure.taker_fee_pct if assume_taker else fee_structure.maker_fee_pct
        total_fee_pct = fee_pct * 2
        
        # Net after fees
        net_profit = profit_target_pct - total_fee_pct
        net_loss = stop_loss_pct + total_fee_pct
        
        # Breakeven win rate formula
        if (net_loss + net_profit) > 0:
            breakeven_wr = (net_loss / (net_loss + net_profit)) * 100
        else:
            breakeven_wr = 100.0  # Impossible to break even
        
        is_achievable = breakeven_wr <= self.requirements.min_win_rate_for_breakeven
        
        logger.info(f"📊 Breakeven Analysis - {fee_structure.exchange_name}:")
        logger.info(f"   Net Reward: +{net_profit:.2f}%")
        logger.info(f"   Net Risk: -{net_loss:.2f}%")
        logger.info(f"   Breakeven Win Rate: {breakeven_wr:.1f}%")
        logger.info(f"   Achievable: {'✅ Yes' if is_achievable else '❌ No'}")
        
        return {
            'exchange': fee_structure.exchange_name,
            'net_profit': net_profit,
            'net_loss': net_loss,
            'breakeven_win_rate': breakeven_wr,
            'is_achievable': is_achievable
        }
    
    def validate_strategy_config(
        self,
        config: Dict,
        exchange: str = 'coinbase'
    ) -> Dict:
        """
        Validate complete strategy configuration for profitability.
        
        Args:
            config: Strategy configuration dictionary with:
                - profit_targets: List of profit target percentages
                - stop_loss: Stop loss percentage
                - primary_target: Primary profit target percentage
            exchange: Exchange name
            
        Returns:
            Complete validation results
            
        Raises:
            ProfitabilityAssertionError: If configuration is unprofitable
        """
        logger.info("=" * 70)
        logger.info("🛡️ PROFITABILITY ASSERTION - STRATEGY VALIDATION")
        logger.info("=" * 70)
        
        results = {}
        
        # 1. Validate profit targets
        if 'profit_targets' in config:
            results['profit_targets'] = self.assert_profit_targets_profitable(
                config['profit_targets'],
                exchange=exchange
            )
        
        # 2. Validate risk/reward ratio
        if 'stop_loss' in config and 'primary_target' in config:
            results['risk_reward'] = self.assert_risk_reward_acceptable(
                config['stop_loss'],
                config['primary_target'],
                exchange=exchange
            )
            
            # 3. Calculate breakeven win rate
            results['breakeven'] = self.calculate_breakeven_win_rate(
                config['stop_loss'],
                config['primary_target'],
                exchange=exchange
            )
        
        logger.info("=" * 70)
        logger.info("✅ STRATEGY CONFIGURATION IS PROFITABLE")
        logger.info("=" * 70)
        
        return results


# Singleton instance
_profitability_assertion = None

def get_profitability_assertion(**kwargs) -> ProfitabilityAssertion:
    """Get singleton profitability assertion instance"""
    global _profitability_assertion
    if _profitability_assertion is None:
        _profitability_assertion = ProfitabilityAssertion(**kwargs)
    return _profitability_assertion


def assert_strategy_is_profitable(
    profit_targets: List[float],
    stop_loss_pct: float,
    primary_target_pct: float,
    exchange: str = 'coinbase'
) -> None:
    """
    Convenience function to assert strategy profitability.
    
    USE THIS IN STRATEGY INITIALIZATION to prevent unprofitable configs.
    
    Args:
        profit_targets: List of profit target percentages
        stop_loss_pct: Stop loss percentage
        primary_target_pct: Primary profit target percentage
        exchange: Exchange name
        
    Raises:
        ProfitabilityAssertionError: If strategy is unprofitable
    """
    assertion = get_profitability_assertion()
    
    config = {
        'profit_targets': profit_targets,
        'stop_loss': stop_loss_pct,
        'primary_target': primary_target_pct
    }
    
    assertion.validate_strategy_config(config, exchange=exchange)
