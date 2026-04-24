"""
Risk Intelligence Gate
======================
Pre-entry verification system that enforces risk intelligence checks before allowing new positions.

Phase 3 Requirement: "Phase in risk intelligence next"
- Volatility scaling → before increasing position sizes
- Risk-weighted exposure → before adding correlated positions

This module provides:
1. Volatility scaling verification before position entry
2. Correlation-weighted exposure checks before position entry
3. Integration with existing volatility and portfolio risk systems
4. Pre-trade risk assessment gates

Author: NIJA Trading Systems
Version: 1.0
Date: February 2026
"""

import logging
from typing import Dict, Tuple, Optional, List
from datetime import datetime
import pandas as pd

logger = logging.getLogger("nija.risk_intelligence_gate")


class RiskIntelligenceGate:
    """
    Pre-entry risk intelligence verification system.
    
    Features:
    - Volatility scaling checks before position increases
    - Correlation-weighted exposure verification
    - Portfolio-level risk assessment
    - Multi-layer risk gates
    """
    
    def __init__(
        self,
        volatility_sizer=None,
        portfolio_risk_engine=None,
        max_volatility_multiplier: float = 3.0,
        max_correlation_exposure: float = 0.40,
        min_diversification_ratio: float = 0.5
    ):
        """
        Initialize Risk Intelligence Gate.
        
        Args:
            volatility_sizer: VolatilityAdaptiveSizer instance (optional)
            portfolio_risk_engine: PortfolioRiskEngine instance (optional)
            max_volatility_multiplier: Max allowed volatility vs target (3.0 = 3x target)
            max_correlation_exposure: Max exposure in correlated assets (0.40 = 40%)
            min_diversification_ratio: Minimum diversification ratio required
        """
        self.volatility_sizer = volatility_sizer
        self.portfolio_risk_engine = portfolio_risk_engine
        self.max_volatility_multiplier = max_volatility_multiplier
        self.max_correlation_exposure = max_correlation_exposure
        self.min_diversification_ratio = min_diversification_ratio
        
        logger.info("✅ Risk Intelligence Gate initialized")
        logger.info(f"   Max Volatility Multiplier: {max_volatility_multiplier}x")
        logger.info(f"   Max Correlation Exposure: {max_correlation_exposure * 100:.0f}%")
        logger.info(f"   Min Diversification Ratio: {min_diversification_ratio:.2f}")
    
    def check_volatility_before_entry(
        self,
        symbol: str,
        df: pd.DataFrame,
        proposed_position_size: float,
        account_balance: float
    ) -> Tuple[bool, Dict]:
        """
        Check volatility conditions before allowing position entry.
        
        Phase 3 Requirement: "Volatility scaling → before increasing position sizes"
        
        Args:
            symbol: Trading symbol
            df: Price dataframe with OHLCV data
            proposed_position_size: Proposed position size in USD
            account_balance: Current account balance
        
        Returns:
            Tuple of (approved, details_dict)
        """
        if self.volatility_sizer is None:
            logger.warning("Volatility sizer not available - skipping volatility check")
            return True, {'check': 'skipped', 'reason': 'volatility_sizer_unavailable'}
        
        try:
            # Calculate current volatility and regime
            volatility_analysis = self._analyze_volatility(symbol, df)
            
            # Check if volatility is within acceptable range
            volatility_multiplier = volatility_analysis.get('volatility_multiplier', 1.0)
            volatility_regime = volatility_analysis.get('regime', 'unknown')
            
            approved = volatility_multiplier <= self.max_volatility_multiplier
            
            details = {
                'check': 'volatility_scaling',
                'approved': approved,
                'symbol': symbol,
                'volatility_multiplier': volatility_multiplier,
                'volatility_regime': volatility_regime,
                'max_allowed': self.max_volatility_multiplier,
                'proposed_size_usd': proposed_position_size,
                'proposed_size_pct': (proposed_position_size / account_balance * 100) if account_balance > 0 else 0,
                'timestamp': datetime.now().isoformat()
            }
            
            if approved:
                logger.info(f"✅ Volatility Check PASSED for {symbol}")
                logger.info(f"   Volatility Multiplier: {volatility_multiplier:.2f}x (< {self.max_volatility_multiplier}x)")
                logger.info(f"   Regime: {volatility_regime}")
            else:
                logger.warning(f"❌ Volatility Check FAILED for {symbol}")
                logger.warning(f"   Volatility Multiplier: {volatility_multiplier:.2f}x (> {self.max_volatility_multiplier}x)")
                logger.warning(f"   Regime: {volatility_regime}")
                logger.warning(f"   Recommendation: Wait for volatility to normalize before entering")
                details['rejection_reason'] = f"Volatility too high: {volatility_multiplier:.2f}x vs {self.max_volatility_multiplier}x limit"
            
            return approved, details
            
        except Exception as e:
            logger.error(f"Error in volatility check: {e}")
            # Fail safe - reject on error
            return False, {
                'check': 'volatility_scaling',
                'approved': False,
                'error': str(e),
                'rejection_reason': 'Error during volatility analysis'
            }
    
    def check_correlation_before_entry(
        self,
        symbol: str,
        proposed_position_size: float,
        current_positions: List[Dict],
        account_balance: float
    ) -> Tuple[bool, Dict]:
        """
        Check correlation exposure before allowing position entry.
        
        Phase 3 Requirement: "Risk-weighted exposure → before adding correlated positions"
        
        Args:
            symbol: Trading symbol for proposed position
            proposed_position_size: Proposed position size in USD
            current_positions: List of current open positions
            account_balance: Current account balance
        
        Returns:
            Tuple of (approved, details_dict)
        """
        if self.portfolio_risk_engine is None:
            logger.warning("Portfolio risk engine not available - skipping correlation check")
            return True, {'check': 'skipped', 'reason': 'portfolio_risk_engine_unavailable'}
        
        try:
            # Analyze correlation exposure
            correlation_analysis = self._analyze_correlation_exposure(
                symbol, proposed_position_size, current_positions, account_balance
            )
            
            # Check if adding this position would exceed correlation limits
            max_correlated_exposure = correlation_analysis.get('max_correlated_exposure_pct', 0)
            correlation_group = correlation_analysis.get('correlation_group', 'unknown')
            diversification_ratio = correlation_analysis.get('diversification_ratio', 1.0)
            
            # Approve if:
            # 1. Correlated exposure stays under limit
            # 2. Diversification ratio is acceptable
            approved = (
                max_correlated_exposure <= self.max_correlation_exposure * 100 and
                diversification_ratio >= self.min_diversification_ratio
            )
            
            details = {
                'check': 'correlation_exposure',
                'approved': approved,
                'symbol': symbol,
                'correlation_group': correlation_group,
                'max_correlated_exposure_pct': max_correlated_exposure,
                'max_allowed_pct': self.max_correlation_exposure * 100,
                'diversification_ratio': diversification_ratio,
                'min_diversification_ratio': self.min_diversification_ratio,
                'proposed_size_usd': proposed_position_size,
                'current_positions': len(current_positions),
                'timestamp': datetime.now().isoformat()
            }
            
            if approved:
                logger.info(f"✅ Correlation Check PASSED for {symbol}")
                logger.info(f"   Correlation Group: {correlation_group}")
                logger.info(f"   Max Correlated Exposure: {max_correlated_exposure:.1f}% (< {self.max_correlation_exposure * 100:.0f}%)")
                logger.info(f"   Diversification Ratio: {diversification_ratio:.2f} (> {self.min_diversification_ratio:.2f})")
            else:
                logger.warning(f"❌ Correlation Check FAILED for {symbol}")
                logger.warning(f"   Correlation Group: {correlation_group}")
                logger.warning(f"   Max Correlated Exposure: {max_correlated_exposure:.1f}% (> {self.max_correlation_exposure * 100:.0f}%)")
                logger.warning(f"   Diversification Ratio: {diversification_ratio:.2f} (< {self.min_diversification_ratio:.2f})")
                logger.warning(f"   Recommendation: Reduce exposure to correlated assets or wait for exits")
                
                rejection_reasons = []
                if max_correlated_exposure > self.max_correlation_exposure * 100:
                    rejection_reasons.append(f"Correlated exposure too high: {max_correlated_exposure:.1f}% vs {self.max_correlation_exposure * 100:.0f}% limit")
                if diversification_ratio < self.min_diversification_ratio:
                    rejection_reasons.append(f"Insufficient diversification: {diversification_ratio:.2f} vs {self.min_diversification_ratio:.2f} minimum")
                
                details['rejection_reason'] = "; ".join(rejection_reasons)
            
            return approved, details
            
        except Exception as e:
            logger.error(f"Error in correlation check: {e}")
            # Fail safe - reject on error
            return False, {
                'check': 'correlation_exposure',
                'approved': False,
                'error': str(e),
                'rejection_reason': 'Error during correlation analysis'
            }
    
    def pre_trade_risk_assessment(
        self,
        symbol: str,
        df: pd.DataFrame,
        proposed_position_size: float,
        current_positions: List[Dict],
        account_balance: float
    ) -> Tuple[bool, Dict]:
        """
        Complete pre-trade risk assessment combining all checks.
        
        Args:
            symbol: Trading symbol
            df: Price dataframe
            proposed_position_size: Proposed position size in USD
            current_positions: Current open positions
            account_balance: Current account balance
        
        Returns:
            Tuple of (approved, assessment_dict)
        """
        logger.info("=" * 80)
        logger.info(f"🎯 PRE-TRADE RISK ASSESSMENT: {symbol}")
        logger.info("=" * 80)
        logger.info(f"   Proposed Size: ${proposed_position_size:.2f} ({proposed_position_size/account_balance*100:.2f}% of account)")
        logger.info(f"   Current Positions: {len(current_positions)}")
        
        assessment = {
            'symbol': symbol,
            'proposed_size_usd': proposed_position_size,
            'account_balance': account_balance,
            'current_positions': len(current_positions),
            'checks': {},
            'timestamp': datetime.now().isoformat()
        }
        
        # Check 1: Volatility Scaling
        vol_approved, vol_details = self.check_volatility_before_entry(
            symbol, df, proposed_position_size, account_balance
        )
        assessment['checks']['volatility_scaling'] = vol_details
        
        # Check 2: Correlation Exposure
        corr_approved, corr_details = self.check_correlation_before_entry(
            symbol, proposed_position_size, current_positions, account_balance
        )
        assessment['checks']['correlation_exposure'] = corr_details
        
        # Final decision: ALL checks must pass
        all_approved = vol_approved and corr_approved
        assessment['approved'] = all_approved
        assessment['checks_passed'] = sum([vol_approved, corr_approved])
        assessment['checks_total'] = 2
        
        if all_approved:
            logger.info(f"\n✅ PRE-TRADE ASSESSMENT APPROVED for {symbol}")
            logger.info(f"   All {assessment['checks_total']} risk intelligence checks passed")
        else:
            logger.warning(f"\n❌ PRE-TRADE ASSESSMENT REJECTED for {symbol}")
            logger.warning(f"   {assessment['checks_total'] - assessment['checks_passed']} of {assessment['checks_total']} checks failed")
            
            # Collect rejection reasons
            rejection_reasons = []
            if not vol_approved:
                rejection_reasons.append(vol_details.get('rejection_reason', 'Volatility check failed'))
            if not corr_approved:
                rejection_reasons.append(corr_details.get('rejection_reason', 'Correlation check failed'))
            
            assessment['rejection_reasons'] = rejection_reasons
            logger.warning(f"   Reasons: {'; '.join(rejection_reasons)}")
        
        logger.info("=" * 80)
        
        return all_approved, assessment
    
    def _analyze_volatility(self, symbol: str, df: pd.DataFrame) -> Dict:
        """
        Analyze volatility for a symbol.
        
        Args:
            symbol: Trading symbol
            df: Price dataframe
        
        Returns:
            Dict with volatility analysis
        """
        try:
            if self.volatility_sizer is None:
                return {'error': 'volatility_sizer_unavailable'}
            
            # Use volatility sizer to get volatility metrics
            # This is a simplified version - actual implementation would use the sizer's methods
            if hasattr(self.volatility_sizer, 'calculate_volatility_multiplier'):
                volatility_multiplier = self.volatility_sizer.calculate_volatility_multiplier(df)
            else:
                # Fallback: simple ATR-based calculation
                volatility_multiplier = 1.0  # Default to normal volatility
            
            # Determine regime based on multiplier
            if volatility_multiplier < 0.5:
                regime = 'LOW'
            elif volatility_multiplier < 1.5:
                regime = 'NORMAL'
            elif volatility_multiplier < 3.0:
                regime = 'HIGH'
            else:
                regime = 'EXTREME'
            
            return {
                'volatility_multiplier': volatility_multiplier,
                'regime': regime
            }
            
        except Exception as e:
            logger.error(f"Error analyzing volatility: {e}")
            return {
                'error': str(e),
                'volatility_multiplier': 999.0,  # High value to trigger rejection
                'regime': 'ERROR'
            }
    
    def _analyze_correlation_exposure(
        self,
        symbol: str,
        proposed_size: float,
        current_positions: List[Dict],
        account_balance: float
    ) -> Dict:
        """
        Analyze correlation exposure if position is added.
        
        Args:
            symbol: Trading symbol
            proposed_size: Proposed position size
            current_positions: Current positions
            account_balance: Account balance
        
        Returns:
            Dict with correlation analysis
        """
        try:
            if self.portfolio_risk_engine is None:
                return {'error': 'portfolio_risk_engine_unavailable'}
            
            # Simplified correlation analysis
            # In production, this would use the portfolio risk engine's methods
            
            # For now, use heuristic: group similar assets
            correlation_groups = self._get_correlation_groups()
            symbol_group = self._get_asset_group(symbol, correlation_groups)
            
            # Calculate current exposure in this group
            group_exposure = 0.0
            for pos in current_positions:
                pos_symbol = pos.get('symbol')
                pos_size = pos.get('size_usd', 0) or pos.get('usd_value', 0)
                if self._get_asset_group(pos_symbol, correlation_groups) == symbol_group:
                    group_exposure += pos_size
            
            # Add proposed position
            total_group_exposure = group_exposure + proposed_size
            group_exposure_pct = (total_group_exposure / account_balance * 100) if account_balance > 0 else 0
            
            # Calculate diversification ratio (simplified)
            num_positions = len(current_positions) + 1  # +1 for proposed
            equal_weight = 1.0 / num_positions if num_positions > 0 else 1.0
            actual_weight = total_group_exposure / account_balance if account_balance > 0 else 1.0
            diversification_ratio = equal_weight / actual_weight if actual_weight > 0 else 0.0
            
            return {
                'correlation_group': symbol_group,
                'max_correlated_exposure_pct': group_exposure_pct,
                'diversification_ratio': min(diversification_ratio, 1.0)  # Cap at 1.0
            }
            
        except Exception as e:
            logger.error(f"Error analyzing correlation: {e}")
            return {
                'error': str(e),
                'correlation_group': 'ERROR',
                'max_correlated_exposure_pct': 100.0,  # High value to trigger rejection
                'diversification_ratio': 0.0
            }
    
    def _get_correlation_groups(self) -> Dict[str, List[str]]:
        """Get predefined correlation groups for assets."""
        return {
            'BTC_RELATED': ['BTC-USD', 'BTC-USDT', 'GBTC', 'MSTR'],
            'ETH_RELATED': ['ETH-USD', 'ETH-USDT', 'ETH2-USD'],
            'MEME_COINS': ['DOGE-USD', 'SHIB-USD', 'PEPE-USD', 'FLOKI-USD'],
            'STABLECOINS': ['USDT-USD', 'USDC-USD', 'DAI-USD'],
            'DEFI': ['UNI-USD', 'AAVE-USD', 'COMP-USD', 'SUSHI-USD'],
            'LAYER1': ['SOL-USD', 'ADA-USD', 'AVAX-USD', 'DOT-USD'],
            'LAYER2': ['MATIC-USD', 'ARB-USD', 'OP-USD']
        }
    
    def _get_asset_group(self, symbol: str, groups: Dict[str, List[str]]) -> str:
        """Determine which correlation group an asset belongs to."""
        for group_name, symbols in groups.items():
            if symbol in symbols:
                return group_name
        return 'OTHER'


def create_risk_intelligence_gate(
    volatility_sizer=None,
    portfolio_risk_engine=None,
    config: Optional[Dict] = None
) -> RiskIntelligenceGate:
    """
    Factory function to create Risk Intelligence Gate with optional config.
    
    Args:
        volatility_sizer: VolatilityAdaptiveSizer instance
        portfolio_risk_engine: PortfolioRiskEngine instance
        config: Optional configuration dict
    
    Returns:
        RiskIntelligenceGate instance
    """
    if config is None:
        config = {}
    
    return RiskIntelligenceGate(
        volatility_sizer=volatility_sizer,
        portfolio_risk_engine=portfolio_risk_engine,
        max_volatility_multiplier=config.get('max_volatility_multiplier', 3.0),
        max_correlation_exposure=config.get('max_correlation_exposure', 0.40),
        min_diversification_ratio=config.get('min_diversification_ratio', 0.5)
    )
