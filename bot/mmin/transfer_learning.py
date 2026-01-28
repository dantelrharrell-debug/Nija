"""
Transfer Learning Engine
========================

Enables pattern transfer across different asset classes:
- Learn patterns from crypto → apply to equities
- Forex signals → crypto execution
- Multi-market pattern recognition
- Cross-domain feature extraction
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
import logging

from .mmin_config import TRANSFER_LEARNING_CONFIG, FEATURE_EXTRACTION_CONFIG

logger = logging.getLogger("nija.mmin.transfer")


@dataclass
class Pattern:
    """Represents a trading pattern"""
    pattern_type: str
    market_source: str
    features: np.ndarray
    confidence: float
    success_rate: float
    metadata: Dict


class TransferLearningEngine:
    """
    Enables transfer learning across asset classes
    
    Features:
    - Extract common patterns from source markets
    - Apply learned patterns to target markets
    - Cross-market feature representation
    - Pattern similarity matching
    - Adaptive learning from outcomes
    """
    
    def __init__(self, config: Dict = None):
        """
        Initialize transfer learning engine
        
        Args:
            config: Optional configuration dictionary
        """
        self.config = config or TRANSFER_LEARNING_CONFIG
        self.feature_config = FEATURE_EXTRACTION_CONFIG
        self.enabled = self.config['enabled']
        
        # Pattern library
        self.learned_patterns: Dict[str, List[Pattern]] = {}
        
        # Transfer performance tracking
        self.transfer_performance: Dict[Tuple[str, str], Dict] = {}
        
        logger.info("TransferLearningEngine initialized")
    
    def extract_features(self, df: pd.DataFrame, market_type: str) -> np.ndarray:
        """
        Extract normalized features from market data
        
        Args:
            df: DataFrame with OHLCV data
            market_type: Type of market (crypto, forex, equities)
            
        Returns:
            Feature vector
        """
        features = []
        
        # Price features
        if len(df) >= 20:
            # Returns
            returns = df['close'].pct_change()
            features.append(returns.mean())
            features.append(returns.std())
            
            # Volatility
            features.append(df['high'].pct_change().std())
            features.append((df['high'] - df['low']).mean() / df['close'].mean())
            
            # Price action
            features.append((df['close'].iloc[-1] - df['open'].iloc[-1]) / df['open'].iloc[-1])
        
        # Technical indicators (simplified for cross-market compatibility)
        if len(df) >= 14:
            # RSI-like momentum
            delta = df['close'].diff()
            gain = delta.where(delta > 0, 0).rolling(window=14).mean()
            loss = -delta.where(delta < 0, 0).rolling(window=14).mean()
            rs = gain / (loss + 1e-10)
            rsi = 100 - (100 / (1 + rs))
            features.append(rsi.iloc[-1] / 100.0)  # Normalize to 0-1
            
            # Trend strength
            sma_20 = df['close'].rolling(window=20).mean()
            trend = (df['close'].iloc[-1] - sma_20.iloc[-1]) / sma_20.iloc[-1]
            features.append(trend)
        
        # Volume features
        if 'volume' in df.columns and len(df) >= 20:
            volume_ma = df['volume'].rolling(window=20).mean()
            volume_ratio = df['volume'].iloc[-1] / volume_ma.iloc[-1]
            features.append(np.log1p(volume_ratio))
        
        # Pad or truncate to fixed size
        target_size = self.config['feature_dimension']
        if len(features) < target_size:
            features.extend([0.0] * (target_size - len(features)))
        elif len(features) > target_size:
            features = features[:target_size]
        
        return np.array(features)
    
    def learn_pattern(self, data: pd.DataFrame, market_type: str,
                     pattern_type: str, outcome: Dict) -> Pattern:
        """
        Learn a pattern from market data
        
        Args:
            data: Market data DataFrame
            market_type: Source market type
            pattern_type: Type of pattern (breakout, reversal, etc.)
            outcome: Trading outcome information
            
        Returns:
            Learned Pattern object
        """
        # Extract features
        features = self.extract_features(data, market_type)
        
        # Calculate confidence based on outcome
        confidence = self._calculate_pattern_confidence(outcome)
        
        # Create pattern
        pattern = Pattern(
            pattern_type=pattern_type,
            market_source=market_type,
            features=features,
            confidence=confidence,
            success_rate=outcome.get('profit', 0.0) > 0,
            metadata={
                'timestamp': data.index[-1] if hasattr(data.index[-1], 'timestamp') else None,
                'outcome': outcome,
            }
        )
        
        # Store in library
        if pattern_type not in self.learned_patterns:
            self.learned_patterns[pattern_type] = []
        self.learned_patterns[pattern_type].append(pattern)
        
        logger.debug(f"Learned {pattern_type} pattern from {market_type} (confidence={confidence:.2f})")
        return pattern
    
    def find_similar_patterns(self, current_data: pd.DataFrame, 
                             market_type: str,
                             pattern_types: List[str] = None,
                             min_confidence: float = 0.5) -> List[Tuple[Pattern, float]]:
        """
        Find similar patterns from library
        
        Args:
            current_data: Current market data
            market_type: Current market type
            pattern_types: Types of patterns to search (None = all)
            min_confidence: Minimum confidence threshold
            
        Returns:
            List of (Pattern, similarity_score) tuples
        """
        if not self.learned_patterns:
            return []
        
        # Extract current features
        current_features = self.extract_features(current_data, market_type)
        
        # Search patterns
        if pattern_types is None:
            pattern_types = list(self.learned_patterns.keys())
        
        similar_patterns = []
        
        for pattern_type in pattern_types:
            if pattern_type in self.learned_patterns:
                for pattern in self.learned_patterns[pattern_type]:
                    # Calculate similarity
                    similarity = self._calculate_similarity(current_features, pattern.features)
                    
                    # Filter by confidence and similarity
                    if pattern.confidence >= min_confidence and similarity >= 0.7:
                        similar_patterns.append((pattern, similarity))
        
        # Sort by similarity
        similar_patterns.sort(key=lambda x: x[1], reverse=True)
        
        logger.debug(f"Found {len(similar_patterns)} similar patterns for {market_type}")
        return similar_patterns
    
    def transfer_pattern(self, pattern: Pattern, target_market: str) -> Dict:
        """
        Transfer a pattern to a different market
        
        Args:
            pattern: Pattern to transfer
            target_market: Target market type
            
        Returns:
            Transfer recommendations
        """
        source_market = pattern.market_source
        
        # Track transfer performance
        transfer_key = (source_market, target_market)
        if transfer_key not in self.transfer_performance:
            self.transfer_performance[transfer_key] = {
                'total_transfers': 0,
                'successful_transfers': 0,
                'avg_confidence': 0.0,
            }
        
        # Adjust confidence based on historical transfer performance
        historical = self.transfer_performance[transfer_key]
        transfer_success_rate = (historical['successful_transfers'] / 
                                max(historical['total_transfers'], 1))
        
        adjusted_confidence = pattern.confidence * (0.5 + 0.5 * transfer_success_rate)
        
        recommendation = {
            'pattern_type': pattern.pattern_type,
            'source_market': source_market,
            'target_market': target_market,
            'original_confidence': pattern.confidence,
            'adjusted_confidence': adjusted_confidence,
            'transfer_success_rate': transfer_success_rate,
            'total_transfers': historical['total_transfers'],
            'recommended': adjusted_confidence >= 0.6,
        }
        
        logger.debug(f"Transfer {pattern.pattern_type}: {source_market} → {target_market} "
                    f"(confidence {pattern.confidence:.2f} → {adjusted_confidence:.2f})")
        
        return recommendation
    
    def update_transfer_outcome(self, source_market: str, target_market: str,
                               successful: bool):
        """
        Update transfer performance tracking
        
        Args:
            source_market: Source market
            target_market: Target market  
            successful: Whether transfer was successful
        """
        transfer_key = (source_market, target_market)
        
        if transfer_key not in self.transfer_performance:
            self.transfer_performance[transfer_key] = {
                'total_transfers': 0,
                'successful_transfers': 0,
                'avg_confidence': 0.0,
            }
        
        stats = self.transfer_performance[transfer_key]
        stats['total_transfers'] += 1
        if successful:
            stats['successful_transfers'] += 1
        
        success_rate = stats['successful_transfers'] / stats['total_transfers']
        logger.info(f"Transfer {source_market} → {target_market}: "
                   f"{stats['successful_transfers']}/{stats['total_transfers']} "
                   f"({success_rate:.1%} success rate)")
    
    def _calculate_pattern_confidence(self, outcome: Dict) -> float:
        """Calculate pattern confidence from outcome"""
        # Base confidence from profit/loss
        profit = outcome.get('profit', 0.0)
        confidence = 0.5  # Neutral
        
        if profit > 0.02:  # >2% profit
            confidence = 0.9
        elif profit > 0.01:  # >1% profit
            confidence = 0.7
        elif profit > 0:  # Any profit
            confidence = 0.6
        elif profit > -0.01:  # Small loss
            confidence = 0.4
        elif profit > -0.02:  # Moderate loss
            confidence = 0.3
        else:  # Large loss
            confidence = 0.1
        
        return confidence
    
    def _calculate_similarity(self, features1: np.ndarray, features2: np.ndarray) -> float:
        """
        Calculate similarity between feature vectors
        
        Uses cosine similarity
        """
        # Normalize features
        norm1 = np.linalg.norm(features1)
        norm2 = np.linalg.norm(features2)
        
        if norm1 == 0 or norm2 == 0:
            return 0.0
        
        # Cosine similarity
        similarity = np.dot(features1, features2) / (norm1 * norm2)
        
        # Convert to 0-1 range
        similarity = (similarity + 1) / 2
        
        return float(similarity)
    
    def get_learning_stats(self) -> Dict:
        """Get transfer learning statistics"""
        total_patterns = sum(len(patterns) for patterns in self.learned_patterns.values())
        
        return {
            'total_patterns': total_patterns,
            'pattern_types': {pt: len(patterns) for pt, patterns in self.learned_patterns.items()},
            'transfer_routes': len(self.transfer_performance),
            'transfer_performance': {
                f"{src}→{tgt}": {
                    'success_rate': stats['successful_transfers'] / max(stats['total_transfers'], 1),
                    'total': stats['total_transfers'],
                }
                for (src, tgt), stats in self.transfer_performance.items()
            },
        }
