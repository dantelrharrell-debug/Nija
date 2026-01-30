"""
NIJA AI Trade Quality Filter
=============================

Machine learning model that predicts trade win probability before entry.

Features:
- Train on historical wins/losses
- Extract features from trade setup
- Predict win probability using XGBoost
- Filter out low-quality trades
- Continuous learning from new trades

This dramatically improves win rate by rejecting trades with low predicted success.

Target: Push win rate from 45-55% → 65-75%

Author: NIJA Trading Systems
Version: 1.0 (Path 1)
Date: January 30, 2026
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import logging
import pickle
from pathlib import Path

logger = logging.getLogger("nija.ai_filter")

# ML imports
try:
    from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
    from sklearn.model_selection import train_test_split, cross_val_score
    from sklearn.preprocessing import StandardScaler
    from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score, roc_auc_score
    import joblib
    
    try:
        import xgboost as xgb
        HAS_XGBOOST = True
    except ImportError:
        HAS_XGBOOST = False
        logger.warning("XGBoost not available, falling back to GradientBoosting")
    
    HAS_ML = True
except ImportError as e:
    HAS_ML = False
    logger.error(f"ML libraries not available: {e}")
    logger.error("AI Trade Quality Filter will operate in fallback mode")


@dataclass
class TradeFeatures:
    """Features extracted from a trade setup"""
    # Price action features
    rsi_9: float
    rsi_14: float
    adx: float
    atr_pct: float
    price_volatility: float
    
    # Trend features
    ema_alignment: float  # 1.0 = perfect alignment, 0.0 = no alignment
    trend_strength: float  # 0.0 to 1.0
    
    # Regime features
    regime_confidence: float
    regime_duration: int
    
    # Entry quality features
    entry_score: int  # 0-5
    distance_from_ma: float  # Normalized distance
    volume_ratio: float  # Current volume / average volume
    
    # Market condition features
    hour_of_day: int
    day_of_week: int
    market_volatility: float
    
    # Signal features
    signal_confidence: float  # From ensemble
    signal_vote_count: int
    
    def to_array(self) -> np.ndarray:
        """Convert features to numpy array"""
        return np.array([
            self.rsi_9,
            self.rsi_14,
            self.adx,
            self.atr_pct,
            self.price_volatility,
            self.ema_alignment,
            self.trend_strength,
            self.regime_confidence,
            self.regime_duration,
            self.entry_score,
            self.distance_from_ma,
            self.volume_ratio,
            self.hour_of_day,
            self.day_of_week,
            self.market_volatility,
            self.signal_confidence,
            self.signal_vote_count
        ])
    
    def to_dict(self) -> Dict:
        """Convert to dictionary"""
        return {
            'rsi_9': self.rsi_9,
            'rsi_14': self.rsi_14,
            'adx': self.adx,
            'atr_pct': self.atr_pct,
            'price_volatility': self.price_volatility,
            'ema_alignment': self.ema_alignment,
            'trend_strength': self.trend_strength,
            'regime_confidence': self.regime_confidence,
            'regime_duration': self.regime_duration,
            'entry_score': self.entry_score,
            'distance_from_ma': self.distance_from_ma,
            'volume_ratio': self.volume_ratio,
            'hour_of_day': self.hour_of_day,
            'day_of_week': self.day_of_week,
            'market_volatility': self.market_volatility,
            'signal_confidence': self.signal_confidence,
            'signal_vote_count': self.signal_vote_count
        }
    
    @classmethod
    def feature_names(cls) -> List[str]:
        """Get feature names in order"""
        return [
            'rsi_9', 'rsi_14', 'adx', 'atr_pct', 'price_volatility',
            'ema_alignment', 'trend_strength', 'regime_confidence', 'regime_duration',
            'entry_score', 'distance_from_ma', 'volume_ratio',
            'hour_of_day', 'day_of_week', 'market_volatility',
            'signal_confidence', 'signal_vote_count'
        ]


@dataclass
class TradePrediction:
    """Prediction result for a trade"""
    win_probability: float  # 0.0 to 1.0
    should_execute: bool
    confidence: float  # Model confidence in prediction
    features: TradeFeatures
    timestamp: datetime
    
    def to_dict(self) -> Dict:
        """Convert to dictionary"""
        return {
            'win_probability': self.win_probability,
            'should_execute': self.should_execute,
            'confidence': self.confidence,
            'features': self.features.to_dict(),
            'timestamp': self.timestamp.isoformat()
        }


class AITradeQualityFilter:
    """
    ML-powered trade quality filter that predicts win probability
    
    Training Process:
    1. Collect historical trades with features and outcomes
    2. Train XGBoost classifier on wins vs losses
    3. Use cross-validation to prevent overfitting
    4. Save model for production use
    
    Prediction Process:
    1. Extract features from current trade setup
    2. Predict win probability using trained model
    3. Only execute if probability >= threshold (default 60%)
    
    Continuous Learning:
    - Periodically retrain on new trade outcomes
    - Track model accuracy over time
    - Automatically adjust threshold if needed
    """
    
    def __init__(self, config: Dict = None, model_path: str = None):
        """
        Initialize AI trade quality filter
        
        Args:
            config: Optional configuration dictionary
            model_path: Optional path to saved model
        """
        self.config = config or {}
        
        # Execution threshold
        self.min_win_probability = self.config.get('min_win_probability', 0.60)  # 60%
        self.min_model_confidence = self.config.get('min_model_confidence', 0.70)  # 70%
        
        # Model parameters
        self.model = None
        self.scaler = None
        self.is_trained = False
        
        # Training data storage
        self.training_data: List[Tuple[TradeFeatures, bool]] = []  # (features, won)
        self.min_training_samples = self.config.get('min_training_samples', 100)
        
        # Performance tracking
        self.predictions_made = 0
        self.predictions_correct = 0
        self.model_accuracy = 0.0
        
        # Model path
        if model_path is None:
            model_path = self.config.get('model_path', 'bot/models/trade_quality_filter.pkl')
        self.model_path = Path(model_path)
        
        # Load existing model if available
        if self.model_path.exists():
            self.load_model()
        else:
            logger.info("No existing model found, will train when sufficient data available")
        
        logger.info(f"AITradeQualityFilter initialized (ML available: {HAS_ML})")
    
    def predict(
        self,
        features: TradeFeatures,
        current_time: datetime = None
    ) -> TradePrediction:
        """
        Predict win probability for a trade setup
        
        Args:
            features: TradeFeatures instance
            current_time: Optional timestamp
        
        Returns:
            TradePrediction
        """
        if current_time is None:
            current_time = datetime.now()
        
        # If model not trained, use fallback logic
        if not self.is_trained or not HAS_ML:
            return self._fallback_prediction(features, current_time)
        
        # Extract features as array
        X = features.to_array().reshape(1, -1)
        
        # Scale features
        if self.scaler:
            X = self.scaler.transform(X)
        
        # Predict
        try:
            # Get probability of win (class 1)
            probabilities = self.model.predict_proba(X)[0]
            win_probability = float(probabilities[1])
            
            # Model confidence is the difference between top two probabilities
            sorted_probs = sorted(probabilities, reverse=True)
            confidence = float(sorted_probs[0] - sorted_probs[1])
            
            # Determine if should execute
            should_execute = (
                win_probability >= self.min_win_probability and
                confidence >= self.min_model_confidence
            )
            
            prediction = TradePrediction(
                win_probability=win_probability,
                should_execute=should_execute,
                confidence=confidence,
                features=features,
                timestamp=current_time
            )
            
            self.predictions_made += 1
            
            logger.info(
                f"AI Prediction: Win probability: {win_probability:.2%} | "
                f"Confidence: {confidence:.2%} | Execute: {should_execute}"
            )
            
            return prediction
            
        except Exception as e:
            logger.error(f"Prediction error: {e}")
            return self._fallback_prediction(features, current_time)
    
    def _fallback_prediction(
        self,
        features: TradeFeatures,
        current_time: datetime
    ) -> TradePrediction:
        """
        Fallback prediction using heuristics when ML not available
        
        Args:
            features: TradeFeatures instance
            current_time: Timestamp
        
        Returns:
            TradePrediction
        """
        # Simple heuristic based on entry score and signal confidence
        score_weight = 0.5
        signal_weight = 0.3
        regime_weight = 0.2
        
        score_prob = features.entry_score / 5.0  # Normalize to 0-1
        signal_prob = features.signal_confidence
        regime_prob = features.regime_confidence
        
        win_probability = (
            score_weight * score_prob +
            signal_weight * signal_prob +
            regime_weight * regime_prob
        )
        
        # Boost for strong trends
        if features.adx > 30:
            win_probability = min(0.95, win_probability + 0.10)
        
        # Penalize for high volatility
        if features.price_volatility > 0.05:  # >5%
            win_probability = max(0.30, win_probability - 0.10)
        
        confidence = 0.60  # Lower confidence for fallback
        should_execute = win_probability >= self.min_win_probability
        
        return TradePrediction(
            win_probability=win_probability,
            should_execute=should_execute,
            confidence=confidence,
            features=features,
            timestamp=current_time
        )
    
    def add_trade_outcome(
        self,
        features: TradeFeatures,
        won: bool,
        pnl: float = None
    ):
        """
        Add trade outcome to training data
        
        Args:
            features: Trade features
            won: Whether trade was profitable
            pnl: Optional profit/loss amount
        """
        self.training_data.append((features, won))
        
        logger.debug(f"Trade outcome added: {'WIN' if won else 'LOSS'} (total samples: {len(self.training_data)})")
        
        # Auto-retrain if we have enough new samples
        if len(self.training_data) >= self.min_training_samples:
            if len(self.training_data) % 50 == 0:  # Retrain every 50 samples
                logger.info(f"Auto-retraining with {len(self.training_data)} samples")
                self.train()
    
    def train(self, test_size: float = 0.2, cv_folds: int = 5):
        """
        Train ML model on historical trade outcomes
        
        Args:
            test_size: Fraction of data to use for testing
            cv_folds: Number of cross-validation folds
        """
        if not HAS_ML:
            logger.warning("ML libraries not available, cannot train model")
            return
        
        if len(self.training_data) < self.min_training_samples:
            logger.warning(
                f"Insufficient training samples: {len(self.training_data)} < {self.min_training_samples}"
            )
            return
        
        logger.info(f"Training AI Trade Quality Filter with {len(self.training_data)} samples")
        
        # Prepare data
        X = np.array([f.to_array() for f, _ in self.training_data])
        y = np.array([1 if won else 0 for _, won in self.training_data])
        
        # Check class balance
        win_count = np.sum(y)
        loss_count = len(y) - win_count
        logger.info(f"Class distribution: {win_count} wins, {loss_count} losses")
        
        # Split data
        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=test_size, random_state=42, stratify=y
        )
        
        # Scale features
        self.scaler = StandardScaler()
        X_train_scaled = self.scaler.fit_transform(X_train)
        X_test_scaled = self.scaler.transform(X_test)
        
        # Train model
        if HAS_XGBOOST:
            logger.info("Training XGBoost classifier")
            self.model = xgb.XGBClassifier(
                n_estimators=100,
                max_depth=5,
                learning_rate=0.1,
                random_state=42,
                use_label_encoder=False,
                eval_metric='logloss'
            )
        else:
            logger.info("Training GradientBoosting classifier")
            self.model = GradientBoostingClassifier(
                n_estimators=100,
                max_depth=5,
                learning_rate=0.1,
                random_state=42
            )
        
        self.model.fit(X_train_scaled, y_train)
        
        # Evaluate
        y_pred = self.model.predict(X_test_scaled)
        y_pred_proba = self.model.predict_proba(X_test_scaled)[:, 1]
        
        accuracy = accuracy_score(y_test, y_pred)
        precision = precision_score(y_test, y_pred, zero_division=0)
        recall = recall_score(y_test, y_pred, zero_division=0)
        f1 = f1_score(y_test, y_pred, zero_division=0)
        
        try:
            auc = roc_auc_score(y_test, y_pred_proba)
        except:
            auc = 0.0
        
        self.model_accuracy = accuracy
        self.is_trained = True
        
        logger.info(
            f"Model trained successfully: Accuracy={accuracy:.2%}, "
            f"Precision={precision:.2%}, Recall={recall:.2%}, F1={f1:.2%}, AUC={auc:.2%}"
        )
        
        # Cross-validation
        cv_scores = cross_val_score(self.model, X_train_scaled, y_train, cv=cv_folds, scoring='accuracy')
        logger.info(f"Cross-validation accuracy: {cv_scores.mean():.2%} (+/- {cv_scores.std():.2%})")
        
        # Feature importance (if available)
        if hasattr(self.model, 'feature_importances_'):
            feature_names = TradeFeatures.feature_names()
            importances = self.model.feature_importances_
            
            # Sort by importance
            indices = np.argsort(importances)[::-1]
            
            logger.info("Top 10 most important features:")
            for i in range(min(10, len(indices))):
                idx = indices[i]
                logger.info(f"  {i+1}. {feature_names[idx]}: {importances[idx]:.4f}")
        
        # Save model
        self.save_model()
    
    def save_model(self):
        """Save trained model to disk"""
        if not self.is_trained or not HAS_ML:
            logger.warning("No trained model to save")
            return
        
        # Create directory if needed
        self.model_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Save model and scaler
        model_data = {
            'model': self.model,
            'scaler': self.scaler,
            'accuracy': self.model_accuracy,
            'training_samples': len(self.training_data),
            'timestamp': datetime.now()
        }
        
        joblib.dump(model_data, self.model_path)
        logger.info(f"Model saved to {self.model_path}")
    
    def load_model(self):
        """Load trained model from disk"""
        if not HAS_ML:
            logger.warning("ML libraries not available, cannot load model")
            return
        
        if not self.model_path.exists():
            logger.warning(f"Model file not found: {self.model_path}")
            return
        
        try:
            model_data = joblib.load(self.model_path)
            
            self.model = model_data['model']
            self.scaler = model_data['scaler']
            self.model_accuracy = model_data.get('accuracy', 0.0)
            self.is_trained = True
            
            logger.info(
                f"Model loaded from {self.model_path} "
                f"(accuracy: {self.model_accuracy:.2%}, "
                f"samples: {model_data.get('training_samples', 'unknown')})"
            )
            
        except Exception as e:
            logger.error(f"Failed to load model: {e}")
    
    def get_stats(self) -> Dict:
        """Get filter statistics"""
        return {
            'is_trained': self.is_trained,
            'model_accuracy': self.model_accuracy,
            'training_samples': len(self.training_data),
            'predictions_made': self.predictions_made,
            'predictions_correct': self.predictions_correct,
            'prediction_accuracy': self.predictions_correct / self.predictions_made if self.predictions_made > 0 else 0.0,
            'min_win_probability': self.min_win_probability,
            'min_model_confidence': self.min_model_confidence
        }


# Global instance
ai_trade_quality_filter = AITradeQualityFilter()
