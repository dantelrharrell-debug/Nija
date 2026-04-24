"""
NIJA Automated Capital Throttle
================================

Implements intelligent capital scaling with risk-of-ruin modeling.

Key Features:
1. Capital scaling gates - Progressive thresholds for capital expansion
2. Parallel risk-of-ruin simulation - Continuous risk assessment
3. 25% drawdown simulation - Stress test before scaling past $50k
4. Dynamic position throttling - Automatic risk adjustment

This system ensures NIJA scales capital safely and maintains discipline
at institutional standards.

Requirements:
- Simulate 25% drawdown before allowing scaling past $50k
- Model risk-of-ruin in parallel with live trading
- Automatically throttle position sizes based on risk metrics
- Maintain capital preservation during adverse conditions

Author: NIJA Trading Systems
Version: 1.0
Date: February 15, 2026
"""

import logging
import numpy as np
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
import json

try:
    from risk_of_ruin_engine import (
        RiskOfRuinEngine,
        RiskOfRuinParameters,
        RiskOfRuinResult
    )
except ImportError:
    from bot.risk_of_ruin_engine import (
        RiskOfRuinEngine,
        RiskOfRuinParameters,
        RiskOfRuinResult
    )

logger = logging.getLogger("nija.capital_throttle")


class ThrottleLevel(Enum):
    """Capital throttle levels"""
    UNRESTRICTED = "unrestricted"  # No throttling
    CONSERVATIVE = "conservative"  # Light throttling
    MODERATE = "moderate"  # Moderate throttling
    STRICT = "strict"  # Heavy throttling
    LOCKED = "locked"  # Capital scaling locked


@dataclass
class CapitalThreshold:
    """Capital threshold configuration"""
    threshold_amount: float  # Dollar threshold
    max_position_size_pct: float  # Max position size at this level
    max_daily_risk_pct: float  # Max daily risk
    required_win_rate: float  # Minimum win rate to pass
    required_profit_factor: float  # Minimum profit factor
    max_drawdown_pct: float  # Maximum allowed drawdown
    simulation_required: bool = False  # Whether stress test required
    
    # Stress test parameters (for $50k+ threshold)
    stress_test_drawdown_pct: float = 25.0
    stress_test_duration_days: int = 30
    min_recovery_speed_pct: float = 50.0  # Must recover 50% of DD in 30 days


@dataclass
class ThrottleConfig:
    """Configuration for capital throttle"""
    # Capital thresholds (progressive gates)
    thresholds: List[CapitalThreshold] = field(default_factory=lambda: [
        # Tier 1: $0 - $10k (Learning phase)
        CapitalThreshold(
            threshold_amount=10000.0,
            max_position_size_pct=0.02,  # 2% max
            max_daily_risk_pct=0.05,  # 5% daily max
            required_win_rate=0.50,
            required_profit_factor=1.2,
            max_drawdown_pct=15.0,
            simulation_required=False
        ),
        # Tier 2: $10k - $25k (Growth phase)
        CapitalThreshold(
            threshold_amount=25000.0,
            max_position_size_pct=0.03,  # 3% max
            max_daily_risk_pct=0.06,
            required_win_rate=0.52,
            required_profit_factor=1.3,
            max_drawdown_pct=12.0,
            simulation_required=False
        ),
        # Tier 3: $25k - $50k (Pre-scaling phase)
        CapitalThreshold(
            threshold_amount=50000.0,
            max_position_size_pct=0.04,  # 4% max
            max_daily_risk_pct=0.08,
            required_win_rate=0.53,
            required_profit_factor=1.4,
            max_drawdown_pct=10.0,
            simulation_required=True,  # 25% DD simulation required
            stress_test_drawdown_pct=25.0,
            stress_test_duration_days=30,
            min_recovery_speed_pct=50.0
        ),
        # Tier 4: $50k+ (Scaled phase - STRICT REQUIREMENTS)
        CapitalThreshold(
            threshold_amount=float('inf'),
            max_position_size_pct=0.05,  # 5% max
            max_daily_risk_pct=0.10,
            required_win_rate=0.55,
            required_profit_factor=1.5,
            max_drawdown_pct=8.0,
            simulation_required=True,
            stress_test_drawdown_pct=25.0,
            stress_test_duration_days=30,
            min_recovery_speed_pct=50.0
        )
    ])
    
    # Risk-of-ruin parameters
    enable_parallel_risk_modeling: bool = True
    risk_update_interval_trades: int = 10  # Update risk model every N trades
    max_acceptable_ruin_probability: float = 0.05  # 5% max ruin probability
    
    # Throttle behavior
    enable_auto_throttle: bool = True
    throttle_on_high_risk: bool = True
    recovery_grace_period_days: int = 7  # Days to wait before re-enabling after throttle


@dataclass
class ThrottleState:
    """Current state of capital throttle"""
    current_capital: float
    current_threshold: CapitalThreshold
    throttle_level: ThrottleLevel
    
    # Performance tracking
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    total_profit: float = 0.0
    total_loss: float = 0.0
    
    # Risk metrics
    current_win_rate: float = 0.50
    current_profit_factor: float = 1.0
    current_drawdown_pct: float = 0.0
    peak_capital: float = 0.0
    
    # Risk-of-ruin tracking
    last_ruin_analysis: Optional[RiskOfRuinResult] = None
    current_ruin_probability: float = 0.0
    
    # Throttle status
    is_throttled: bool = False
    throttle_reason: str = ""
    throttle_start_time: Optional[datetime] = None
    
    # Stress test status (for $50k threshold)
    stress_test_passed: bool = False
    stress_test_last_run: Optional[datetime] = None
    stress_test_results: Optional[Dict] = None
    
    last_updated: datetime = field(default_factory=datetime.now)


class AutomatedCapitalThrottle:
    """
    Automated Capital Throttle System
    
    Responsibilities:
    1. Monitor capital levels and enforce progressive thresholds
    2. Run parallel risk-of-ruin simulations
    3. Execute 25% drawdown stress tests before $50k scaling
    4. Automatically throttle position sizes based on risk
    5. Track performance metrics and enforce requirements
    """
    
    # Data persistence
    DATA_DIR = Path(__file__).parent.parent / "data"
    THROTTLE_FILE = DATA_DIR / "capital_throttle_state.json"
    
    def __init__(
        self,
        initial_capital: float,
        config: Optional[ThrottleConfig] = None
    ):
        """
        Initialize Automated Capital Throttle
        
        Args:
            initial_capital: Starting capital
            config: Throttle configuration
        """
        self.config = config or ThrottleConfig()
        self.initial_capital = initial_capital
        
        # Initialize state
        initial_threshold = self._get_threshold_for_capital(initial_capital)
        self.state = ThrottleState(
            current_capital=initial_capital,
            current_threshold=initial_threshold,
            throttle_level=ThrottleLevel.UNRESTRICTED,
            peak_capital=initial_capital
        )
        
        # Risk-of-ruin engine
        self.risk_engine: Optional[RiskOfRuinEngine] = None
        
        # Ensure data directory exists
        self.DATA_DIR.mkdir(parents=True, exist_ok=True)
        
        # Load existing state
        self._load_state()
        
        logger.info("=" * 70)
        logger.info("🎯 Automated Capital Throttle Initialized")
        logger.info("=" * 70)
        logger.info(f"Initial Capital: ${initial_capital:,.2f}")
        logger.info(f"Current Threshold: ${self.state.current_threshold.threshold_amount:,.2f}")
        logger.info(f"Max Position Size: {self.state.current_threshold.max_position_size_pct*100:.2f}%")
        logger.info(f"Parallel Risk Modeling: {'ENABLED' if self.config.enable_parallel_risk_modeling else 'DISABLED'}")
        logger.info("=" * 70)
    
    def _get_threshold_for_capital(self, capital: float) -> CapitalThreshold:
        """Get appropriate threshold for capital level"""
        for threshold in self.config.thresholds:
            if capital < threshold.threshold_amount:
                return threshold
        # Return highest threshold if capital exceeds all
        return self.config.thresholds[-1]
    
    def update_capital(self, current_capital: float) -> None:
        """
        Update current capital and check if threshold changed
        
        Args:
            current_capital: Updated capital amount
        """
        old_threshold = self.state.current_threshold
        new_threshold = self._get_threshold_for_capital(current_capital)
        
        self.state.current_capital = current_capital
        
        # Update peak
        if current_capital > self.state.peak_capital:
            self.state.peak_capital = current_capital
        
        # Calculate drawdown
        if self.state.peak_capital > 0:
            self.state.current_drawdown_pct = (
                (self.state.peak_capital - current_capital) / self.state.peak_capital * 100
            )
        
        # Check if threshold changed
        if new_threshold.threshold_amount != old_threshold.threshold_amount:
            logger.info(f"📊 Capital threshold changed: ${old_threshold.threshold_amount:,.2f} → ${new_threshold.threshold_amount:,.2f}")
            self.state.current_threshold = new_threshold
            
            # Check if stress test required
            if new_threshold.simulation_required and not self.state.stress_test_passed:
                logger.warning(f"⚠️ Stress test required before scaling to ${new_threshold.threshold_amount:,.2f}")
                self._throttle_capital("STRESS_TEST_REQUIRED")
        
        self.state.last_updated = datetime.now()
        self._save_state()
    
    def record_trade(
        self,
        is_winner: bool,
        profit_loss: float
    ) -> None:
        """
        Record trade outcome and update metrics
        
        Args:
            is_winner: Whether trade was profitable
            profit_loss: Profit or loss amount
        """
        self.state.total_trades += 1
        
        if is_winner:
            self.state.winning_trades += 1
            self.state.total_profit += abs(profit_loss)
        else:
            self.state.losing_trades += 1
            self.state.total_loss += abs(profit_loss)
        
        # Update win rate
        if self.state.total_trades > 0:
            self.state.current_win_rate = self.state.winning_trades / self.state.total_trades
        
        # Update profit factor
        if self.state.total_loss > 0:
            self.state.current_profit_factor = self.state.total_profit / self.state.total_loss
        
        # Check if we should run parallel risk analysis
        if self.config.enable_parallel_risk_modeling:
            if self.state.total_trades % self.config.risk_update_interval_trades == 0:
                self._run_parallel_risk_analysis()
        
        # Check throttle conditions
        self._check_throttle_conditions()
        
        self._save_state()
    
    def _run_parallel_risk_analysis(self) -> None:
        """Run parallel risk-of-ruin analysis"""
        if self.state.total_trades < 20:
            logger.debug("Insufficient trade history for risk analysis")
            return
        
        logger.info("🎲 Running parallel risk-of-ruin analysis...")
        
        # Calculate average win/loss
        avg_win = self.state.total_profit / max(1, self.state.winning_trades)
        avg_loss = self.state.total_loss / max(1, self.state.losing_trades)
        
        # Normalize to R multiples (assume risk = avg_loss)
        avg_win_r = avg_win / max(1, avg_loss)
        avg_loss_r = 1.0
        
        # Ensure win rate is valid
        win_rate = max(0.01, min(0.99, self.state.current_win_rate))
        
        # Create risk parameters
        params = RiskOfRuinParameters(
            win_rate=win_rate,
            avg_win=avg_win_r,
            avg_loss=avg_loss_r,
            initial_capital=self.state.current_capital,
            position_size_pct=self.state.current_threshold.max_position_size_pct,
            ruin_threshold_pct=0.50,
            num_simulations=5000  # Reduced for speed in parallel execution
        )
        
        # Run analysis
        self.risk_engine = RiskOfRuinEngine(params)
        result = self.state.last_ruin_analysis = self.risk_engine.analyze()
        self.state.current_ruin_probability = result.simulated_ruin_probability
        
        logger.info(f"📊 Risk-of-Ruin: {result.simulated_ruin_probability:.2%} (Rating: {result.risk_rating})")
        
        # Check if ruin probability too high
        if result.simulated_ruin_probability > self.config.max_acceptable_ruin_probability:
            logger.warning(f"⚠️ Ruin probability ({result.simulated_ruin_probability:.2%}) exceeds maximum ({self.config.max_acceptable_ruin_probability:.2%})")
            if self.config.throttle_on_high_risk:
                self._throttle_capital("HIGH_RUIN_RISK")
    
    def simulate_drawdown_stress_test(
        self,
        drawdown_pct: float = 25.0,
        duration_days: int = 30
    ) -> Dict:
        """
        Simulate a severe drawdown scenario
        
        This is required before scaling past $50k to ensure the strategy
        can handle severe market conditions.
        
        Args:
            drawdown_pct: Drawdown percentage to simulate
            duration_days: Duration of drawdown in days
        
        Returns:
            Dictionary with stress test results
        """
        logger.info("=" * 70)
        logger.info(f"🔥 STRESS TEST: Simulating {drawdown_pct:.1f}% Drawdown")
        logger.info("=" * 70)
        
        if self.state.total_trades < 50:
            logger.warning("⚠️ Insufficient trade history for reliable stress test (need 50+ trades)")
            return {
                'passed': False,
                'reason': 'insufficient_history',
                'trades_needed': 50 - self.state.total_trades
            }
        
        # Use current performance metrics
        win_rate = self.state.current_win_rate
        profit_factor = self.state.current_profit_factor
        
        # Calculate avg win/loss in R
        avg_win_r = profit_factor if profit_factor > 1 else 1.5
        avg_loss_r = 1.0
        
        # Simulate drawdown scenario
        starting_capital = self.state.current_capital
        capital = starting_capital * (1 - drawdown_pct / 100)  # Start at drawdown
        
        logger.info(f"Starting Capital: ${starting_capital:,.2f}")
        logger.info(f"Drawdown Capital: ${capital:,.2f}")
        logger.info(f"Recovery Target: ${starting_capital * (1 - drawdown_pct / 100 * 0.5):,.2f} (50% recovery)")
        
        # Simulate trading during recovery
        trades_per_day = 3  # Conservative estimate
        total_trades = duration_days * trades_per_day
        recovery_target = starting_capital * (1 - drawdown_pct / 100 * 0.5)  # 50% recovery
        
        recovered_simulations = 0
        num_simulations = 1000
        
        for sim in range(num_simulations):
            sim_capital = capital
            
            for trade in range(total_trades):
                risk_amount = sim_capital * self.state.current_threshold.max_position_size_pct
                
                # Simulate trade
                if np.random.random() < win_rate:
                    sim_capital += risk_amount * avg_win_r
                else:
                    sim_capital -= risk_amount * avg_loss_r
                
                # Check if recovered
                if sim_capital >= recovery_target:
                    recovered_simulations += 1
                    break
        
        recovery_probability = recovered_simulations / num_simulations
        
        # Determine if passed
        required_recovery = self.state.current_threshold.min_recovery_speed_pct / 100
        passed = recovery_probability >= required_recovery
        
        logger.info(f"\n📊 Stress Test Results:")
        logger.info(f"  Recovery Probability: {recovery_probability:.2%}")
        logger.info(f"  Required: {required_recovery:.2%}")
        logger.info(f"  Status: {'✅ PASSED' if passed else '❌ FAILED'}")
        logger.info("=" * 70)
        
        results = {
            'passed': passed,
            'recovery_probability': recovery_probability,
            'required_probability': required_recovery,
            'drawdown_pct': drawdown_pct,
            'duration_days': duration_days,
            'timestamp': datetime.now().isoformat()
        }
        
        # Update state
        self.state.stress_test_passed = passed
        self.state.stress_test_last_run = datetime.now()
        self.state.stress_test_results = results
        
        if passed:
            logger.info("✅ Stress test PASSED - Capital scaling approved")
            self._unthrottle_capital()
        else:
            logger.warning("❌ Stress test FAILED - Capital scaling blocked")
            self._throttle_capital("STRESS_TEST_FAILED")
        
        self._save_state()
        
        return results
    
    def _check_throttle_conditions(self) -> None:
        """Check if throttling should be applied"""
        if not self.config.enable_auto_throttle:
            return
        
        threshold = self.state.current_threshold
        
        # Check win rate
        if self.state.current_win_rate < threshold.required_win_rate:
            self._throttle_capital(f"WIN_RATE_LOW ({self.state.current_win_rate:.2%} < {threshold.required_win_rate:.2%})")
            return
        
        # Check profit factor
        if self.state.current_profit_factor < threshold.required_profit_factor:
            self._throttle_capital(f"PROFIT_FACTOR_LOW ({self.state.current_profit_factor:.2f} < {threshold.required_profit_factor:.2f})")
            return
        
        # Check drawdown
        if self.state.current_drawdown_pct > threshold.max_drawdown_pct:
            self._throttle_capital(f"DRAWDOWN_EXCEEDED ({self.state.current_drawdown_pct:.1f}% > {threshold.max_drawdown_pct:.1f}%)")
            return
        
        # If all conditions met and was throttled, unthrottle
        if self.state.is_throttled and self.state.throttle_reason not in ["STRESS_TEST_REQUIRED", "STRESS_TEST_FAILED"]:
            self._unthrottle_capital()
    
    def _throttle_capital(self, reason: str) -> None:
        """Apply capital throttle"""
        if not self.state.is_throttled:
            logger.warning(f"🔒 CAPITAL THROTTLED: {reason}")
            self.state.is_throttled = True
            self.state.throttle_reason = reason
            self.state.throttle_start_time = datetime.now()
            self.state.throttle_level = ThrottleLevel.STRICT
    
    def _unthrottle_capital(self) -> None:
        """Remove capital throttle"""
        if self.state.is_throttled:
            logger.info(f"🔓 CAPITAL UNTHROTTLED (was: {self.state.throttle_reason})")
            self.state.is_throttled = False
            self.state.throttle_reason = ""
            self.state.throttle_level = ThrottleLevel.UNRESTRICTED
    
    def get_max_position_size(self) -> float:
        """
        Get maximum position size percentage
        
        Returns throttled position size if conditions not met
        
        Returns:
            Maximum position size as percentage (0-1)
        """
        base_size = self.state.current_threshold.max_position_size_pct
        
        if not self.state.is_throttled:
            return base_size
        
        # Apply throttling based on level
        if self.state.throttle_level == ThrottleLevel.LOCKED:
            return 0.0
        elif self.state.throttle_level == ThrottleLevel.STRICT:
            return base_size * 0.25  # 25% of normal
        elif self.state.throttle_level == ThrottleLevel.MODERATE:
            return base_size * 0.50  # 50% of normal
        elif self.state.throttle_level == ThrottleLevel.CONSERVATIVE:
            return base_size * 0.75  # 75% of normal
        else:
            return base_size
    
    def get_status_report(self) -> Dict:
        """
        Generate comprehensive status report
        
        Returns:
            Dictionary with throttle status and metrics
        """
        return {
            'capital': {
                'current': self.state.current_capital,
                'peak': self.state.peak_capital,
                'drawdown_pct': self.state.current_drawdown_pct
            },
            'threshold': {
                'amount': self.state.current_threshold.threshold_amount,
                'max_position_size_pct': self.state.current_threshold.max_position_size_pct,
                'required_win_rate': self.state.current_threshold.required_win_rate,
                'required_profit_factor': self.state.current_threshold.required_profit_factor,
                'simulation_required': self.state.current_threshold.simulation_required
            },
            'performance': {
                'total_trades': self.state.total_trades,
                'win_rate': self.state.current_win_rate,
                'profit_factor': self.state.current_profit_factor,
                'winning_trades': self.state.winning_trades,
                'losing_trades': self.state.losing_trades
            },
            'risk': {
                'ruin_probability': self.state.current_ruin_probability,
                'max_acceptable': self.config.max_acceptable_ruin_probability,
                'last_analysis': self.state.last_ruin_analysis.timestamp if self.state.last_ruin_analysis else None
            },
            'throttle': {
                'is_throttled': self.state.is_throttled,
                'reason': self.state.throttle_reason,
                'level': self.state.throttle_level.value,
                'max_position_size': self.get_max_position_size()
            },
            'stress_test': {
                'passed': self.state.stress_test_passed,
                'last_run': self.state.stress_test_last_run.isoformat() if self.state.stress_test_last_run else None,
                'results': self.state.stress_test_results
            }
        }
    
    def _save_state(self) -> None:
        """Save throttle state to disk"""
        try:
            state_data = {
                'current_capital': self.state.current_capital,
                'peak_capital': self.state.peak_capital,
                'current_drawdown_pct': self.state.current_drawdown_pct,
                'total_trades': self.state.total_trades,
                'winning_trades': self.state.winning_trades,
                'losing_trades': self.state.losing_trades,
                'total_profit': self.state.total_profit,
                'total_loss': self.state.total_loss,
                'current_win_rate': self.state.current_win_rate,
                'current_profit_factor': self.state.current_profit_factor,
                'current_ruin_probability': self.state.current_ruin_probability,
                'is_throttled': self.state.is_throttled,
                'throttle_reason': self.state.throttle_reason,
                'throttle_level': self.state.throttle_level.value,
                'stress_test_passed': self.state.stress_test_passed,
                'stress_test_last_run': self.state.stress_test_last_run.isoformat() if self.state.stress_test_last_run else None,
                'stress_test_results': self.state.stress_test_results,
                'last_updated': self.state.last_updated.isoformat()
            }
            
            with open(self.THROTTLE_FILE, 'w') as f:
                json.dump(state_data, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save throttle state: {e}")
    
    def _load_state(self) -> None:
        """Load throttle state from disk"""
        if not self.THROTTLE_FILE.exists():
            return
        
        try:
            with open(self.THROTTLE_FILE, 'r') as f:
                state_data = json.load(f)
            
            # Restore state
            self.state.current_capital = state_data.get('current_capital', self.initial_capital)
            self.state.peak_capital = state_data.get('peak_capital', self.initial_capital)
            self.state.current_drawdown_pct = state_data.get('current_drawdown_pct', 0.0)
            self.state.total_trades = state_data.get('total_trades', 0)
            self.state.winning_trades = state_data.get('winning_trades', 0)
            self.state.losing_trades = state_data.get('losing_trades', 0)
            self.state.total_profit = state_data.get('total_profit', 0.0)
            self.state.total_loss = state_data.get('total_loss', 0.0)
            self.state.current_win_rate = state_data.get('current_win_rate', 0.50)
            self.state.current_profit_factor = state_data.get('current_profit_factor', 1.0)
            self.state.current_ruin_probability = state_data.get('current_ruin_probability', 0.0)
            self.state.is_throttled = state_data.get('is_throttled', False)
            self.state.throttle_reason = state_data.get('throttle_reason', "")
            self.state.throttle_level = ThrottleLevel(state_data.get('throttle_level', 'unrestricted'))
            self.state.stress_test_passed = state_data.get('stress_test_passed', False)
            
            if state_data.get('stress_test_last_run'):
                self.state.stress_test_last_run = datetime.fromisoformat(state_data['stress_test_last_run'])
            
            self.state.stress_test_results = state_data.get('stress_test_results')
            
            logger.info(f"📂 Loaded throttle state from disk (Trades: {self.state.total_trades})")
        except Exception as e:
            logger.error(f"Failed to load throttle state: {e}")


# Example usage and testing
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format='%(levelname)s - %(message)s')
    
    print("\n" + "=" * 70)
    print("AUTOMATED CAPITAL THROTTLE - DEMONSTRATION")
    print("=" * 70)
    
    # Initialize throttle with $10k
    throttle = AutomatedCapitalThrottle(initial_capital=10000.0)
    
    # Simulate trading to $50k
    print("\n📈 Simulating growth from $10k to $50k...")
    capital = 10000.0
    
    for i in range(100):
        # Simulate 60% win rate
        is_winner = np.random.random() < 0.60
        pnl = 200 if is_winner else -100
        
        capital += pnl
        throttle.update_capital(capital)
        throttle.record_trade(is_winner, pnl)
        
        if i % 20 == 0:
            status = throttle.get_status_report()
            print(f"\nTrade {i}: Capital=${capital:,.2f}, WR={status['performance']['win_rate']:.2%}, Throttled={status['throttle']['is_throttled']}")
    
    # At $50k, run stress test
    print("\n" + "=" * 70)
    print("STRESS TEST AT $50K THRESHOLD")
    print("=" * 70)
    
    results = throttle.simulate_drawdown_stress_test(
        drawdown_pct=25.0,
        duration_days=30
    )
    
    # Print final status
    print("\n" + "=" * 70)
    print("FINAL STATUS")
    print("=" * 70)
    
    status = throttle.get_status_report()
    print(json.dumps(status, indent=2, default=str))
