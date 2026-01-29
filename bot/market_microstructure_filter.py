"""
NIJA Market Microstructure Filter Enhancement
==============================================

GOD-TIER ENHANCEMENT #3: Advanced market microstructure analysis to avoid
poor trading conditions:
1. Liquidity depth analysis (order book depth)
2. Spread expansion detection (market stress indicator)
3. Order book imbalance detection
4. Low-liquidity period identification
5. Market impact estimation

Avoids trading during periods of poor market quality that lead to
slippage, poor fills, and increased risk.

Author: NIJA Trading Systems
Version: 1.0 - God-Tier Edition
Date: January 2026
"""

import pandas as pd
import numpy as np
from typing import Dict, Tuple, List, Optional
from enum import Enum
from datetime import datetime, time
import logging

logger = logging.getLogger("nija.microstructure")


class LiquidityQuality(Enum):
    """Liquidity quality classifications"""
    EXCELLENT = "excellent"  # Tight spreads, deep book
    GOOD = "good"            # Normal conditions
    FAIR = "fair"            # Slightly degraded
    POOR = "poor"            # Wide spreads or thin book
    CRITICAL = "critical"    # Avoid trading


class MarketMicrostructureFilter:
    """
    Advanced market microstructure analysis and filtering
    
    Key Features:
    - Real-time spread monitoring with expansion detection
    - Liquidity depth analysis from order book
    - Order flow imbalance detection
    - Time-of-day liquidity patterns
    - Market impact estimation for position sizing
    """
    
    def __init__(self, config: Dict = None):
        """
        Initialize Market Microstructure Filter
        
        Args:
            config: Optional configuration dictionary
        """
        self.config = config or {}
        
        # Spread thresholds (as percentage of mid price)
        self.spread_thresholds = {
            LiquidityQuality.EXCELLENT: 0.0005,  # 0.05% (5 bps)
            LiquidityQuality.GOOD: 0.0010,       # 0.10% (10 bps)
            LiquidityQuality.FAIR: 0.0020,       # 0.20% (20 bps)
            LiquidityQuality.POOR: 0.0050,       # 0.50% (50 bps)
            # Anything above POOR is CRITICAL
        }
        
        # Spread expansion detection
        self.spread_expansion_threshold = 2.0  # 2x normal spread = expansion
        self.spread_lookback = 20  # Periods for average spread calculation
        
        # Order book depth thresholds (in USD)
        self.min_depth_excellent = 100000  # $100k on each side
        self.min_depth_good = 50000        # $50k on each side
        self.min_depth_fair = 25000        # $25k on each side
        self.min_depth_poor = 10000        # $10k on each side
        
        # Order book imbalance thresholds
        self.imbalance_threshold_minor = 0.20  # 20% imbalance = minor
        self.imbalance_threshold_major = 0.40  # 40% imbalance = major
        
        # Market impact estimation parameters
        self.market_impact_coefficient = 0.0001  # Base market impact factor
        
        # Time-of-day liquidity patterns (UTC hours)
        self.high_liquidity_hours = [
            (13, 16),  # London-NY overlap
            (14, 20),  # NY session
        ]
        self.low_liquidity_hours = [
            (22, 4),   # Late night / early morning
            (0, 1),    # Weekend transitions
        ]
        
        logger.info("✅ Market Microstructure Filter initialized")
        logger.info(f"   Spread expansion threshold: {self.spread_expansion_threshold}x")
        logger.info(f"   Min depth (good): ${self.min_depth_good:,.0f}")
    
    def analyze_market_quality(
        self,
        symbol: str,
        bid_price: float,
        ask_price: float,
        bid_size: Optional[float] = None,
        ask_size: Optional[float] = None,
        order_book: Optional[Dict] = None,
        spread_history: Optional[pd.Series] = None,
        current_time: Optional[datetime] = None
    ) -> Dict:
        """
        Comprehensive market quality analysis
        
        Args:
            symbol: Trading pair symbol
            bid_price: Current best bid price
            ask_price: Current best ask price
            bid_size: Size at best bid (optional)
            ask_size: Size at best ask (optional)
            order_book: Full order book data (optional)
            spread_history: Historical spread data (optional)
            current_time: Current timestamp (optional, defaults to now)
            
        Returns:
            Dictionary with market quality analysis
        """
        current_time = current_time or datetime.now()
        
        # 1. Analyze spread
        spread_analysis = self._analyze_spread(
            bid_price=bid_price,
            ask_price=ask_price,
            spread_history=spread_history
        )
        
        # 2. Analyze liquidity depth
        depth_analysis = self._analyze_liquidity_depth(
            bid_price=bid_price,
            ask_price=ask_price,
            bid_size=bid_size,
            ask_size=ask_size,
            order_book=order_book
        )
        
        # 3. Analyze order book imbalance
        imbalance_analysis = self._analyze_order_imbalance(
            bid_size=bid_size,
            ask_size=ask_size,
            order_book=order_book
        )
        
        # 4. Assess time-of-day liquidity
        tod_analysis = self._analyze_time_of_day_liquidity(current_time)
        
        # 5. Determine overall liquidity quality
        overall_quality = self._determine_overall_quality(
            spread_analysis=spread_analysis,
            depth_analysis=depth_analysis,
            imbalance_analysis=imbalance_analysis,
            tod_analysis=tod_analysis
        )
        
        # 6. Generate trading recommendation
        can_trade, reasons = self._generate_trading_recommendation(
            overall_quality=overall_quality,
            spread_analysis=spread_analysis,
            depth_analysis=depth_analysis,
            imbalance_analysis=imbalance_analysis
        )
        
        # Compile comprehensive results
        result = {
            'symbol': symbol,
            'timestamp': current_time,
            'can_trade': can_trade,
            'overall_quality': overall_quality.value,
            'reasons': reasons,
            'spread': spread_analysis,
            'depth': depth_analysis,
            'imbalance': imbalance_analysis,
            'time_of_day': tod_analysis,
        }
        
        logger.info(f"🔍 Market Quality Analysis ({symbol}):")
        logger.info(f"   Overall Quality: {overall_quality.value.upper()}")
        logger.info(f"   Spread: {spread_analysis['spread_pct']*10000:.1f} bps ({spread_analysis['quality'].value})")
        logger.info(f"   Depth Quality: {depth_analysis['quality'].value}")
        logger.info(f"   Can Trade: {can_trade}")
        
        return result
    
    def _analyze_spread(
        self,
        bid_price: float,
        ask_price: float,
        spread_history: Optional[pd.Series] = None
    ) -> Dict:
        """
        Analyze bid-ask spread and detect expansion
        
        Args:
            bid_price: Current best bid
            ask_price: Current best ask
            spread_history: Historical spread data
            
        Returns:
            Spread analysis dictionary
        """
        if bid_price <= 0 or ask_price <= 0:
            return {
                'spread_absolute': 0,
                'spread_pct': 0,
                'quality': LiquidityQuality.CRITICAL,
                'expansion_detected': False,
                'expansion_ratio': 0,
            }
        
        # Calculate current spread
        mid_price = (bid_price + ask_price) / 2
        spread_absolute = ask_price - bid_price
        spread_pct = spread_absolute / mid_price if mid_price > 0 else 0
        
        # Classify spread quality
        quality = LiquidityQuality.CRITICAL
        for qual, threshold in sorted(self.spread_thresholds.items(), key=lambda x: x[1]):
            if spread_pct <= threshold:
                quality = qual
                break
        
        # Detect spread expansion
        expansion_detected = False
        expansion_ratio = 1.0
        
        if spread_history is not None and len(spread_history) >= self.spread_lookback:
            avg_spread = spread_history.tail(self.spread_lookback).mean()
            if avg_spread > 0:
                expansion_ratio = spread_pct / avg_spread
                expansion_detected = expansion_ratio >= self.spread_expansion_threshold
        
        return {
            'spread_absolute': spread_absolute,
            'spread_pct': spread_pct,
            'spread_bps': spread_pct * 10000,  # Basis points
            'quality': quality,
            'expansion_detected': expansion_detected,
            'expansion_ratio': expansion_ratio,
        }
    
    def _analyze_liquidity_depth(
        self,
        bid_price: float,
        ask_price: float,
        bid_size: Optional[float] = None,
        ask_size: Optional[float] = None,
        order_book: Optional[Dict] = None
    ) -> Dict:
        """
        Analyze liquidity depth from order book
        
        Args:
            bid_price: Best bid price
            ask_price: Best ask price
            bid_size: Size at best bid
            ask_size: Size at best ask
            order_book: Full order book with bids/asks lists
            
        Returns:
            Liquidity depth analysis dictionary
        """
        # Calculate depth from top of book
        if bid_size is not None and ask_size is not None:
            bid_depth_usd = bid_size * bid_price
            ask_depth_usd = ask_size * ask_price
            total_depth_usd = bid_depth_usd + ask_depth_usd
        else:
            bid_depth_usd = 0
            ask_depth_usd = 0
            total_depth_usd = 0
        
        # If full order book available, calculate deeper levels
        if order_book is not None:
            # Aggregate depth within 0.5% of mid price
            mid_price = (bid_price + ask_price) / 2
            depth_range = mid_price * 0.005  # 0.5%
            
            bid_depth_aggregate = self._aggregate_order_book_side(
                orders=order_book.get('bids', []),
                reference_price=mid_price,
                max_distance=depth_range,
                is_bid=True
            )
            
            ask_depth_aggregate = self._aggregate_order_book_side(
                orders=order_book.get('asks', []),
                reference_price=mid_price,
                max_distance=depth_range,
                is_bid=False
            )
            
            total_depth_usd = bid_depth_aggregate + ask_depth_aggregate
        
        # Classify depth quality
        if total_depth_usd >= self.min_depth_excellent * 2:
            quality = LiquidityQuality.EXCELLENT
        elif total_depth_usd >= self.min_depth_good * 2:
            quality = LiquidityQuality.GOOD
        elif total_depth_usd >= self.min_depth_fair * 2:
            quality = LiquidityQuality.FAIR
        elif total_depth_usd >= self.min_depth_poor * 2:
            quality = LiquidityQuality.POOR
        else:
            quality = LiquidityQuality.CRITICAL
        
        return {
            'bid_depth_usd': bid_depth_usd,
            'ask_depth_usd': ask_depth_usd,
            'total_depth_usd': total_depth_usd,
            'quality': quality,
        }
    
    def _aggregate_order_book_side(
        self,
        orders: List[List],
        reference_price: float,
        max_distance: float,
        is_bid: bool
    ) -> float:
        """
        Aggregate order book depth within price range
        
        NOTE: This function assumes orders are sorted by price.
        For bids: descending order (highest first)
        For asks: ascending order (lowest first)
        
        Args:
            orders: List of [price, size] orders (must be price-sorted)
            reference_price: Reference price for distance calculation
            max_distance: Maximum price distance to include
            is_bid: True for bids, False for asks
            
        Returns:
            Total depth in USD within range
        """
        total_depth = 0.0
        
        for order in orders:
            if len(order) < 2:
                continue
            
            price = float(order[0])
            size = float(order[1])
            
            # Calculate distance from reference
            distance = abs(price - reference_price)
            
            # Only include orders within range
            if distance <= max_distance:
                total_depth += price * size
            elif is_bid and price < reference_price - max_distance:
                # For bids, once we're too far below reference, can break
                break
            elif not is_bid and price > reference_price + max_distance:
                # For asks, once we're too far above reference, can break
                break
        
        return total_depth
    
    def _analyze_order_imbalance(
        self,
        bid_size: Optional[float] = None,
        ask_size: Optional[float] = None,
        order_book: Optional[Dict] = None
    ) -> Dict:
        """
        Analyze order book imbalance
        
        Imbalance can indicate directional pressure or liquidity issues.
        
        Args:
            bid_size: Size at best bid
            ask_size: Size at best ask
            order_book: Full order book
            
        Returns:
            Imbalance analysis dictionary
        """
        if bid_size is None or ask_size is None or bid_size + ask_size == 0:
            return {
                'imbalance_ratio': 0,
                'imbalance_direction': 'neutral',
                'imbalance_severity': 'none',
            }
        
        # Calculate imbalance ratio (-1 to 1, negative = bid heavy, positive = ask heavy)
        total_size = bid_size + ask_size
        imbalance_ratio = (ask_size - bid_size) / total_size
        
        # Determine direction
        if imbalance_ratio > 0.05:
            direction = 'ask_heavy'  # More sellers (bearish)
        elif imbalance_ratio < -0.05:
            direction = 'bid_heavy'  # More buyers (bullish)
        else:
            direction = 'balanced'
        
        # Determine severity
        abs_imbalance = abs(imbalance_ratio)
        if abs_imbalance >= self.imbalance_threshold_major:
            severity = 'major'
        elif abs_imbalance >= self.imbalance_threshold_minor:
            severity = 'minor'
        else:
            severity = 'balanced'
        
        return {
            'imbalance_ratio': imbalance_ratio,
            'imbalance_direction': direction,
            'imbalance_severity': severity,
            'bid_size': bid_size,
            'ask_size': ask_size,
        }
    
    def _analyze_time_of_day_liquidity(self, current_time: datetime) -> Dict:
        """
        Assess liquidity based on time of day
        
        Args:
            current_time: Current timestamp
            
        Returns:
            Time-of-day analysis dictionary
        """
        hour = current_time.hour
        
        # Check if in high liquidity hours
        in_high_liquidity = any(
            start <= hour < end for start, end in self.high_liquidity_hours
        )
        
        # Check if in low liquidity hours
        in_low_liquidity = any(
            start <= hour < end or (start > end and (hour >= start or hour < end))
            for start, end in self.low_liquidity_hours
        )
        
        # Determine session
        if 13 <= hour < 16:
            session = 'overlap'  # London-NY overlap
            quality = LiquidityQuality.EXCELLENT
        elif 14 <= hour < 20:
            session = 'ny'
            quality = LiquidityQuality.GOOD
        elif 8 <= hour < 14:
            session = 'london'
            quality = LiquidityQuality.GOOD
        elif 0 <= hour < 8:
            session = 'asia'
            quality = LiquidityQuality.FAIR
        else:
            session = 'off_hours'
            quality = LiquidityQuality.POOR
        
        return {
            'session': session,
            'hour': hour,
            'quality': quality,
            'in_high_liquidity': in_high_liquidity,
            'in_low_liquidity': in_low_liquidity,
        }
    
    def _determine_overall_quality(
        self,
        spread_analysis: Dict,
        depth_analysis: Dict,
        imbalance_analysis: Dict,
        tod_analysis: Dict
    ) -> LiquidityQuality:
        """
        Determine overall liquidity quality from component analyses
        
        Uses worst-case approach with some leniency.
        
        Args:
            spread_analysis: Spread analysis results
            depth_analysis: Depth analysis results
            imbalance_analysis: Imbalance analysis results
            tod_analysis: Time-of-day analysis results
            
        Returns:
            Overall LiquidityQuality enum
        """
        # Get quality levels
        spread_quality = spread_analysis['quality']
        depth_quality = depth_analysis['quality']
        tod_quality = tod_analysis['quality']
        
        # Map qualities to numeric scores
        quality_scores = {
            LiquidityQuality.EXCELLENT: 5,
            LiquidityQuality.GOOD: 4,
            LiquidityQuality.FAIR: 3,
            LiquidityQuality.POOR: 2,
            LiquidityQuality.CRITICAL: 1,
        }
        
        # Calculate weighted average score
        spread_score = quality_scores[spread_quality]
        depth_score = quality_scores[depth_quality]
        tod_score = quality_scores[tod_quality]
        
        # Spread and depth are most important
        avg_score = (spread_score * 0.5 + depth_score * 0.3 + tod_score * 0.2)
        
        # Penalty for major imbalance
        if imbalance_analysis['imbalance_severity'] == 'major':
            avg_score -= 0.5
        
        # Map back to quality level
        if avg_score >= 4.5:
            return LiquidityQuality.EXCELLENT
        elif avg_score >= 3.5:
            return LiquidityQuality.GOOD
        elif avg_score >= 2.5:
            return LiquidityQuality.FAIR
        elif avg_score >= 1.5:
            return LiquidityQuality.POOR
        else:
            return LiquidityQuality.CRITICAL
    
    def _generate_trading_recommendation(
        self,
        overall_quality: LiquidityQuality,
        spread_analysis: Dict,
        depth_analysis: Dict,
        imbalance_analysis: Dict
    ) -> Tuple[bool, List[str]]:
        """
        Generate trading recommendation based on market quality
        
        Args:
            overall_quality: Overall liquidity quality
            spread_analysis: Spread analysis
            depth_analysis: Depth analysis
            imbalance_analysis: Imbalance analysis
            
        Returns:
            Tuple of (can_trade, reasons list)
        """
        reasons = []
        
        # Critical quality = no trading
        if overall_quality == LiquidityQuality.CRITICAL:
            reasons.append("Critical market quality - avoid trading")
            return False, reasons
        
        # Poor quality = avoid trading
        if overall_quality == LiquidityQuality.POOR:
            reasons.append("Poor market quality - avoid trading")
            return False, reasons
        
        # Spread expansion = warning
        if spread_analysis.get('expansion_detected', False):
            reasons.append(f"Spread expansion detected ({spread_analysis['expansion_ratio']:.1f}x normal)")
            if spread_analysis['expansion_ratio'] >= 3.0:
                return False, reasons
        
        # Major imbalance = caution
        if imbalance_analysis['imbalance_severity'] == 'major':
            reasons.append(f"Major order imbalance ({imbalance_analysis['imbalance_direction']})")
            # Don't block trading, but warn
        
        # Fair or better quality = can trade
        reasons.append(f"Market quality: {overall_quality.value}")
        return True, reasons
    
    def estimate_market_impact(
        self,
        order_size_usd: float,
        depth_analysis: Dict,
        spread_analysis: Dict
    ) -> Dict:
        """
        Estimate market impact of a trade
        
        Args:
            order_size_usd: Order size in USD
            depth_analysis: Liquidity depth analysis
            spread_analysis: Spread analysis
            
        Returns:
            Market impact estimation dictionary
        """
        total_depth = depth_analysis['total_depth_usd']
        spread_pct = spread_analysis['spread_pct']
        
        # Simple market impact model
        # Impact = spread/2 + (order_size / depth) * impact_coefficient
        
        spread_cost = spread_pct / 2  # Pay half the spread
        
        if total_depth > 0:
            depth_impact = (order_size_usd / total_depth) * self.market_impact_coefficient
        else:
            depth_impact = spread_pct  # Assume full spread if no depth data
        
        total_impact_pct = spread_cost + depth_impact
        total_impact_usd = order_size_usd * total_impact_pct
        
        # Classify impact severity
        if total_impact_pct < 0.001:  # < 10 bps
            severity = 'minimal'
        elif total_impact_pct < 0.002:  # < 20 bps
            severity = 'low'
        elif total_impact_pct < 0.005:  # < 50 bps
            severity = 'moderate'
        elif total_impact_pct < 0.010:  # < 100 bps
            severity = 'high'
        else:
            severity = 'excessive'
        
        return {
            'impact_pct': total_impact_pct,
            'impact_bps': total_impact_pct * 10000,
            'impact_usd': total_impact_usd,
            'spread_cost_pct': spread_cost,
            'depth_impact_pct': depth_impact,
            'severity': severity,
            'order_to_depth_ratio': order_size_usd / total_depth if total_depth > 0 else 0,
        }


def get_microstructure_filter(config: Dict = None) -> MarketMicrostructureFilter:
    """
    Factory function to create MarketMicrostructureFilter instance
    
    Args:
        config: Optional configuration dictionary
        
    Returns:
        MarketMicrostructureFilter instance
    """
    return MarketMicrostructureFilter(config)


# Example usage and testing
if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.INFO, format='%(levelname)s - %(message)s')
    
    # Create microstructure filter
    msfilter = get_microstructure_filter()
    
    # Test with sample market data
    result = msfilter.analyze_market_quality(
        symbol='BTC-USD',
        bid_price=50000.0,
        ask_price=50005.0,  # 5 USD spread = 0.01% = 10 bps
        bid_size=10.0,      # $500k
        ask_size=8.0,       # $400k
        current_time=datetime(2024, 1, 15, 15, 30)  # NY session
    )
    
    print(f"\n{'='*70}")
    print(f"Market Quality Analysis Results:")
    print(f"{'='*70}")
    print(f"Symbol: {result['symbol']}")
    print(f"Overall Quality: {result['overall_quality'].upper()}")
    print(f"Can Trade: {result['can_trade']}")
    print(f"Spread: {result['spread']['spread_bps']:.1f} bps ({result['spread']['quality'].value})")
    print(f"Depth: ${result['depth']['total_depth_usd']:,.0f} ({result['depth']['quality'].value})")
    print(f"Imbalance: {result['imbalance']['imbalance_severity']} ({result['imbalance']['imbalance_direction']})")
    print(f"Session: {result['time_of_day']['session'].upper()}")
    print(f"\nReasons: {', '.join(result['reasons'])}")
    
    # Test market impact estimation
    impact = msfilter.estimate_market_impact(
        order_size_usd=50000.0,  # $50k order
        depth_analysis=result['depth'],
        spread_analysis=result['spread']
    )
    
    print(f"\n{'='*70}")
    print(f"Market Impact Estimation:")
    print(f"{'='*70}")
    print(f"Order Size: $50,000")
    print(f"Impact: {impact['impact_bps']:.1f} bps (${impact['impact_usd']:.2f})")
    print(f"Severity: {impact['severity'].upper()}")
    print(f"Order/Depth Ratio: {impact['order_to_depth_ratio']*100:.1f}%")
