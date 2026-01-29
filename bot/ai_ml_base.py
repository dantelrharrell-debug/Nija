"""
NIJA AI ML Base Module - Pluggable Machine Learning Interface

This module provides an extensible base class for integrating ML models into the trading system.
Currently implements rule-based scoring with hooks for future ML model integration.

Features:
- Pluggable model interface (base class for any ML model)
- Real-time regime and momentum scoring
- Live data logging for future model training
- Signal confidence calculation
- Feature extraction from market data

Future ML Integration Points:
- TODO: Train LSTM/Transformer for price prediction
- TODO: Train Random Forest for pattern classification
- TODO: Train Gradient Boosting for momentum scoring
- TODO: Implement online learning for continuous adaptation
- TODO: Add ensemble model combining multiple predictors

Author: NIJA Trading Systems
Version: 1.0
Date: December 2024
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime
import logging
import json
import os

logger = logging.getLogger("nija.ai_ml")


class MLModelInterface:
    """
    Base interface for pluggable ML models.

    Any ML model (sklearn, tensorflow, pytorch, etc.) should implement this interface
    to integrate seamlessly with the NIJA trading system.
    """

    def __init__(self, model_name: str = "base_model"):
        """
        Initialize ML model interface.

        Args:
            model_name: Identifier for this model
        """
        self.model_name = model_name
        self.is_trained = False
        self.feature_names: List[str] = []
        logger.info(f"ML Model Interface initialized: {model_name}")

    def train(self, features: pd.DataFrame, labels: pd.Series, **kwargs) -> Dict:
        """
        Train the ML model.

        Args:
            features: Training features DataFrame
            labels: Training labels Series
            **kwargs: Additional training parameters

        Returns:
            dict: Training metrics and results

        TODO: Implement actual ML training (sklearn, tensorflow, etc.)
        """
        raise NotImplementedError("Subclasses must implement train()")

    def predict(self, features: pd.DataFrame) -> np.ndarray:
        """
        Make predictions using the trained model.

        Args:
            features: Features DataFrame for prediction

        Returns:
            np.ndarray: Predictions

        TODO: Implement actual ML prediction
        """
        raise NotImplementedError("Subclasses must implement predict()")

    def predict_proba(self, features: pd.DataFrame) -> np.ndarray:
        """
        Get prediction probabilities (for classification models).

        Args:
            features: Features DataFrame

        Returns:
            np.ndarray: Prediction probabilities

        TODO: Implement probability prediction for uncertainty quantification
        """
        raise NotImplementedError("Subclasses must implement predict_proba()")

    def save_model(self, filepath: str) -> bool:
        """
        Save trained model to disk.

        Args:
            filepath: Path to save model

        Returns:
            bool: Success status

        TODO: Implement model serialization
        """
        logger.warning(f"Model save not implemented for {self.model_name}")
        return False

    def load_model(self, filepath: str) -> bool:
        """
        Load trained model from disk.

        Args:
            filepath: Path to load model from

        Returns:
            bool: Success status

        TODO: Implement model deserialization
        """
        logger.warning(f"Model load not implemented for {self.model_name}")
        return False


class RuleBasedModel(MLModelInterface):
    """
    Rule-based model that mimics ML interface.

    This serves as the default model until actual ML models are trained.
    Uses technical analysis rules to generate predictions.
    """

    def __init__(self):
        """Initialize rule-based model."""
        super().__init__(model_name="rule_based_v1")
        self.is_trained = True  # Rules don't need training
        logger.info("Rule-based model initialized (default until ML models available)")

    def train(self, features: pd.DataFrame, labels: pd.Series, **kwargs) -> Dict:
        """Rule-based model doesn't require training."""
        logger.info("Rule-based model is always 'trained' - no training needed")
        return {"status": "success", "message": "Rule-based model ready"}

    def predict(self, features: pd.DataFrame) -> np.ndarray:
        """
        Generate predictions using rule-based logic.

        Args:
            features: Features DataFrame with technical indicators

        Returns:
            np.ndarray: Predictions (-1 for bearish, 0 for neutral, 1 for bullish)
        """
        predictions = []

        for idx in range(len(features)):
            score = self._calculate_rule_score(features.iloc[idx])

            if score > 0.6:
                predictions.append(1)  # Bullish
            elif score < 0.4:
                predictions.append(-1)  # Bearish
            else:
                predictions.append(0)  # Neutral

        return np.array(predictions)

    def predict_proba(self, features: pd.DataFrame) -> np.ndarray:
        """
        Get prediction confidence scores.

        Args:
            features: Features DataFrame

        Returns:
            np.ndarray: Confidence scores (0-1)
        """
        probabilities = []

        for idx in range(len(features)):
            score = self._calculate_rule_score(features.iloc[idx])
            probabilities.append(score)

        return np.array(probabilities)

    def _calculate_rule_score(self, row: pd.Series) -> float:
        """
        Calculate rule-based score from features.

        Args:
            row: Single row of features

        Returns:
            float: Score from 0 to 1
        """
        score = 0.5  # Neutral baseline

        # Trend indicators (+/- 0.15)
        if 'adx' in row and row['adx'] > 25:
            trend_strength = min((row['adx'] - 25) / 25, 1.0) * 0.15
            if 'ema_alignment' in row and row['ema_alignment'] == 1:
                score += trend_strength
            elif 'ema_alignment' in row and row['ema_alignment'] == -1:
                score -= trend_strength

        # Momentum indicators (+/- 0.15)
        if 'rsi' in row:
            if row['rsi'] > 70:
                score += 0.10
            elif row['rsi'] < 30:
                score -= 0.10
            elif 40 < row['rsi'] < 60:
                score += 0.05  # Neutral RSI is good

        # Volume confirmation (+/- 0.10)
        if 'volume_ratio' in row and row['volume_ratio'] > 1.5:
            score += 0.10
        elif 'volume_ratio' in row and row['volume_ratio'] < 0.5:
            score -= 0.10

        # Volatility (+/- 0.10)
        if 'atr_pct' in row:
            if 0.005 <= row['atr_pct'] <= 0.02:
                score += 0.10  # Optimal volatility
            elif row['atr_pct'] > 0.03:
                score -= 0.10  # Too volatile

        return np.clip(score, 0.0, 1.0)


class LiveDataLogger:
    """
    Logs live market data and trading signals for future ML model training.

    This logger captures:
    - Market features (technical indicators)
    - Trading signals and decisions
    - Actual outcomes (profit/loss)
    - Timestamps and metadata

    Data can be used later to train supervised ML models.
    """

    def __init__(self, log_dir: str = "./data/ml_training"):
        """
        Initialize live data logger.

        Args:
            log_dir: Directory to store training data logs
        """
        self.log_dir = log_dir
        os.makedirs(log_dir, exist_ok=True)

        self.features_log_file = os.path.join(log_dir, "features_log.csv")
        self.signals_log_file = os.path.join(log_dir, "signals_log.csv")
        self.outcomes_log_file = os.path.join(log_dir, "outcomes_log.csv")

        logger.info(f"Live data logger initialized: {log_dir}")

    def log_features(self, timestamp: datetime, symbol: str,
                    features: Dict[str, float]) -> None:
        """
        Log market features at a specific timestamp.

        Args:
            timestamp: When features were captured
            symbol: Trading symbol
            features: Dictionary of feature name -> value
        """
        try:
            # Prepare data row
            data = {
                'timestamp': timestamp.isoformat(),
                'symbol': symbol,
                **features
            }

            # Append to CSV
            df = pd.DataFrame([data])

            if os.path.exists(self.features_log_file):
                df.to_csv(self.features_log_file, mode='a', header=False, index=False)
            else:
                df.to_csv(self.features_log_file, mode='w', header=True, index=False)

        except Exception as e:
            logger.error(f"Error logging features: {e}")

    def log_signal(self, timestamp: datetime, symbol: str, signal_type: str,
                  confidence: float, features_snapshot: Dict[str, float]) -> str:
        """
        Log a trading signal.

        Args:
            timestamp: When signal was generated
            symbol: Trading symbol
            signal_type: 'long', 'short', or 'neutral'
            confidence: Signal confidence (0-1)
            features_snapshot: Market features at signal time

        Returns:
            str: Unique signal ID for tracking outcomes
        """
        try:
            signal_id = f"{symbol}_{timestamp.strftime('%Y%m%d_%H%M%S')}"

            data = {
                'signal_id': signal_id,
                'timestamp': timestamp.isoformat(),
                'symbol': symbol,
                'signal_type': signal_type,
                'confidence': confidence,
                'features': json.dumps(features_snapshot)
            }

            df = pd.DataFrame([data])

            if os.path.exists(self.signals_log_file):
                df.to_csv(self.signals_log_file, mode='a', header=False, index=False)
            else:
                df.to_csv(self.signals_log_file, mode='w', header=True, index=False)

            return signal_id

        except Exception as e:
            logger.error(f"Error logging signal: {e}")
            return ""

    def log_outcome(self, signal_id: str, outcome: str, pnl: float,
                   duration_minutes: int, exit_reason: str) -> None:
        """
        Log the outcome of a trade.

        Args:
            signal_id: ID from log_signal()
            outcome: 'win', 'loss', or 'breakeven'
            pnl: Profit/loss in dollars
            duration_minutes: How long trade was held
            exit_reason: Why trade was exited
        """
        try:
            data = {
                'signal_id': signal_id,
                'timestamp': datetime.now().isoformat(),
                'outcome': outcome,
                'pnl': pnl,
                'duration_minutes': duration_minutes,
                'exit_reason': exit_reason
            }

            df = pd.DataFrame([data])

            if os.path.exists(self.outcomes_log_file):
                df.to_csv(self.outcomes_log_file, mode='a', header=False, index=False)
            else:
                df.to_csv(self.outcomes_log_file, mode='w', header=True, index=False)

        except Exception as e:
            logger.error(f"Error logging outcome: {e}")

    def get_training_data(self) -> Optional[Tuple[pd.DataFrame, pd.Series]]:
        """
        Load logged data for ML training.

        Returns:
            Tuple of (features, labels) or None if insufficient data

        TODO: Implement data preprocessing and label generation
        TODO: Handle missing values and outliers
        TODO: Create features from raw indicators
        TODO: Generate labels from outcomes (win/loss)
        """
        try:
            if not os.path.exists(self.signals_log_file) or \
               not os.path.exists(self.outcomes_log_file):
                logger.warning("Insufficient logged data for training")
                return None

            signals_df = pd.read_csv(self.signals_log_file)
            outcomes_df = pd.read_csv(self.outcomes_log_file)

            # Merge signals with outcomes
            merged = signals_df.merge(outcomes_df, on='signal_id', how='inner')

            if len(merged) < 100:
                logger.warning(f"Only {len(merged)} samples - need at least 100 for training")
                return None

            # TODO: Extract features from JSON
            # TODO: Generate labels from outcomes
            # TODO: Preprocess and normalize

            logger.info(f"Loaded {len(merged)} samples for training")
            return None  # Placeholder until implemented

        except Exception as e:
            logger.error(f"Error loading training data: {e}")
            return None


class EnhancedAIEngine:
    """
    Enhanced AI engine with pluggable ML models and live data logging.

    This is the main interface for the trading system to interact with AI/ML.
    It coordinates between models, logging, and prediction.
    """

    def __init__(self, model: Optional[MLModelInterface] = None,
                 enable_logging: bool = True):
        """
        Initialize enhanced AI engine.

        Args:
            model: ML model instance (defaults to RuleBasedModel)
            enable_logging: Whether to log data for future training
        """
        self.model = model or RuleBasedModel()
        self.enable_logging = enable_logging

        if enable_logging:
            self.data_logger = LiveDataLogger()
        else:
            self.data_logger = None

        logger.info(f"Enhanced AI Engine initialized with {self.model.model_name}")

    def _get_indicator_value(self, indicator_val, default=0):
        """
        Safely extract scalar value from indicator (handles Series or scalar).

        Args:
            indicator_val: Value that may be Series, scalar, or dict
            default: Default value if extraction fails

        Returns:
            Scalar value
        """
        if hasattr(indicator_val, 'iloc'):
            return indicator_val.iloc[-1]
        elif isinstance(indicator_val, (int, float)):
            return indicator_val
        else:
            return default

    def extract_features(self, df: pd.DataFrame, indicators: Dict) -> Dict[str, float]:
        """
        Extract ML features from market data and indicators.

        Args:
            df: OHLCV DataFrame
            indicators: Calculated technical indicators

        Returns:
            dict: Feature name -> value mapping
        """
        features = {}

        # Trend features
        features['adx'] = self._get_indicator_value(indicators.get('adx', 0))
        features['ema_9'] = self._get_indicator_value(indicators.get('ema_9', 0))
        features['ema_21'] = self._get_indicator_value(indicators.get('ema_21', 0))
        features['ema_50'] = self._get_indicator_value(indicators.get('ema_50', 0))

        # Calculate EMA alignment
        if features['ema_9'] > features['ema_21'] > features['ema_50']:
            features['ema_alignment'] = 1  # Bullish
        elif features['ema_9'] < features['ema_21'] < features['ema_50']:
            features['ema_alignment'] = -1  # Bearish
        else:
            features['ema_alignment'] = 0  # Mixed

        # Momentum features
        features['rsi'] = self._get_indicator_value(indicators.get('rsi', 50))

        macd = indicators.get('macd', {})
        if isinstance(macd, dict):
            features['macd_line'] = self._get_indicator_value(macd.get('macd_line', 0))
            features['macd_signal'] = self._get_indicator_value(macd.get('signal', 0))
            features['macd_histogram'] = self._get_indicator_value(macd.get('histogram', 0))
        else:
            features['macd_line'] = 0
            features['macd_signal'] = 0
            features['macd_histogram'] = 0

        # Volatility features
        features['atr'] = self._get_indicator_value(indicators.get('atr', 0))
        current_price = df['close'].iloc[-1]
        features['atr_pct'] = features['atr'] / current_price if current_price > 0 else 0

        # Volume features
        if len(df) >= 20:
            avg_volume = df['volume'].iloc[-20:].mean()
            current_volume = df['volume'].iloc[-1]
            features['volume_ratio'] = current_volume / avg_volume if avg_volume > 0 else 0
        else:
            features['volume_ratio'] = 1.0

        # Price features
        features['close_price'] = current_price
        features['vwap'] = self._get_indicator_value(indicators.get('vwap', current_price))
        features['price_vs_vwap'] = (current_price - features['vwap']) / features['vwap'] if features['vwap'] > 0 else 0

        return features

    def predict_signal(self, df: pd.DataFrame, indicators: Dict,
                      symbol: str) -> Dict[str, Any]:
        """
        Generate trading signal with confidence score.

        Args:
            df: OHLCV DataFrame
            indicators: Technical indicators
            symbol: Trading symbol

        Returns:
            dict: {
                'signal': str ('long', 'short', 'neutral'),
                'confidence': float (0-1),
                'score': float (0-100),
                'features': dict,
                'signal_id': str (if logging enabled)
            }
        """
        # Extract features
        features = self.extract_features(df, indicators)

        # Create features DataFrame for model
        features_df = pd.DataFrame([features])

        # Get prediction and confidence
        prediction = self.model.predict(features_df)[0]
        confidence = self.model.predict_proba(features_df)[0]

        # Convert prediction to signal
        if prediction == 1:
            signal = 'long'
        elif prediction == -1:
            signal = 'short'
        else:
            signal = 'neutral'

        # Calculate score (0-100)
        score = confidence * 100

        # Log if enabled
        signal_id = ""
        if self.enable_logging and self.data_logger:
            timestamp = datetime.now()
            self.data_logger.log_features(timestamp, symbol, features)
            signal_id = self.data_logger.log_signal(
                timestamp, symbol, signal, confidence, features
            )

        return {
            'signal': signal,
            'confidence': confidence,
            'score': score,
            'features': features,
            'signal_id': signal_id
        }

    def log_trade_outcome(self, signal_id: str, outcome: str, pnl: float,
                         duration_minutes: int, exit_reason: str) -> None:
        """
        Log the outcome of a trade for future model training.

        Args:
            signal_id: ID returned from predict_signal()
            outcome: 'win', 'loss', or 'breakeven'
            pnl: Profit/loss in dollars
            duration_minutes: Trade duration
            exit_reason: Why trade was exited
        """
        if self.enable_logging and self.data_logger and signal_id:
            self.data_logger.log_outcome(
                signal_id, outcome, pnl, duration_minutes, exit_reason
            )
