"""
NIJA Portfolio Super-State Machine
==================================

Portfolio-level state machine that sits above the trading state machine and
manages high-level portfolio states based on market conditions, risk metrics,
and performance.

This super-state machine coordinates:
- Trading state machine (OFF, DRY_RUN, LIVE_ACTIVE, etc.)
- Sector cap state layer (sector exposure limits)
- Portfolio state (position management, capital allocation)
- Market conditions (normal, stressed, crisis, recovery)

States:
    NORMAL - Regular trading operations, all systems nominal
    CAUTIOUS - Elevated risk, tighter controls
    STRESSED - High volatility, reduced position sizing
    CRISIS - Market crash conditions, defensive mode
    RECOVERY - Post-crisis recovery, gradual position rebuilding
    EMERGENCY_HALT - Immediate halt of all operations

Author: NIJA Trading Systems
Version: 1.0
Date: February 2026
"""

import logging
import threading
from enum import Enum
from typing import Dict, Optional, List, Callable, Any, Tuple
from dataclasses import dataclass, field
from datetime import datetime
import json
import os

from bot.trading_state_machine import TradingStateMachine, TradingState, get_state_machine
from bot.sector_cap_state import SectorCapState, SectorCapStateManager, get_sector_cap_manager
from bot.portfolio_state import PortfolioState, PortfolioStateManager, get_portfolio_manager

logger = logging.getLogger("nija.portfolio_super_state")


class PortfolioSuperState(Enum):
    """Portfolio-level states that coordinate all subsystems"""
    NORMAL = "normal"
    CAUTIOUS = "cautious"
    STRESSED = "stressed"
    CRISIS = "crisis"
    RECOVERY = "recovery"
    EMERGENCY_HALT = "emergency_halt"


@dataclass
class MarketConditions:
    """Current market conditions that influence portfolio state"""
    # Volatility metrics
    current_volatility: float = 0.02  # 2% normal
    volatility_30d_avg: float = 0.02
    volatility_zscore: float = 0.0  # Standard deviations from mean
    
    # Drawdown metrics
    current_drawdown: float = 0.0  # Current drawdown from peak
    max_drawdown_30d: float = 0.0
    
    # Liquidity metrics
    avg_spread_bps: float = 10.0  # Average spread in basis points
    liquidity_score: float = 1.0  # 1.0 = normal, 0.0 = no liquidity
    
    # Correlation
    avg_correlation: float = 0.5  # Average inter-asset correlation
    
    # Market sentiment
    fear_greed_index: float = 50.0  # 0 = extreme fear, 100 = extreme greed
    
    # Portfolio health
    portfolio_utilization: float = 0.0  # % of capital deployed
    sector_concentration: float = 0.0  # Max sector exposure %
    
    # Performance
    pnl_7d_pct: float = 0.0
    pnl_30d_pct: float = 0.0
    win_rate_7d: float = 0.0
    
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class PortfolioStateRules:
    """Rules for portfolio state management in each super-state"""
    max_position_size_pct: float
    max_portfolio_utilization_pct: float
    max_sector_exposure_pct: float
    min_cash_reserve_pct: float
    max_concurrent_positions: int
    require_stop_losses: bool
    allow_new_positions: bool
    force_position_reduction: bool
    risk_multiplier: float  # Scales all risk limits


# Define rules for each portfolio state
PORTFOLIO_STATE_RULES: Dict[PortfolioSuperState, PortfolioStateRules] = {
    PortfolioSuperState.NORMAL: PortfolioStateRules(
        max_position_size_pct=15.0,
        max_portfolio_utilization_pct=85.0,
        max_sector_exposure_pct=20.0,
        min_cash_reserve_pct=15.0,
        max_concurrent_positions=10,
        require_stop_losses=True,
        allow_new_positions=True,
        force_position_reduction=False,
        risk_multiplier=1.0
    ),
    PortfolioSuperState.CAUTIOUS: PortfolioStateRules(
        max_position_size_pct=12.0,
        max_portfolio_utilization_pct=75.0,
        max_sector_exposure_pct=18.0,
        min_cash_reserve_pct=25.0,
        max_concurrent_positions=8,
        require_stop_losses=True,
        allow_new_positions=True,
        force_position_reduction=False,
        risk_multiplier=0.8
    ),
    PortfolioSuperState.STRESSED: PortfolioStateRules(
        max_position_size_pct=8.0,
        max_portfolio_utilization_pct=60.0,
        max_sector_exposure_pct=15.0,
        min_cash_reserve_pct=40.0,
        max_concurrent_positions=5,
        require_stop_losses=True,
        allow_new_positions=False,
        force_position_reduction=True,
        risk_multiplier=0.5
    ),
    PortfolioSuperState.CRISIS: PortfolioStateRules(
        max_position_size_pct=5.0,
        max_portfolio_utilization_pct=30.0,
        max_sector_exposure_pct=10.0,
        min_cash_reserve_pct=70.0,
        max_concurrent_positions=3,
        require_stop_losses=True,
        allow_new_positions=False,
        force_position_reduction=True,
        risk_multiplier=0.25
    ),
    PortfolioSuperState.RECOVERY: PortfolioStateRules(
        max_position_size_pct=10.0,
        max_portfolio_utilization_pct=70.0,
        max_sector_exposure_pct=16.0,
        min_cash_reserve_pct=30.0,
        max_concurrent_positions=6,
        require_stop_losses=True,
        allow_new_positions=True,
        force_position_reduction=False,
        risk_multiplier=0.7
    ),
    PortfolioSuperState.EMERGENCY_HALT: PortfolioStateRules(
        max_position_size_pct=0.0,
        max_portfolio_utilization_pct=0.0,
        max_sector_exposure_pct=0.0,
        min_cash_reserve_pct=100.0,
        max_concurrent_positions=0,
        require_stop_losses=True,
        allow_new_positions=False,
        force_position_reduction=True,
        risk_multiplier=0.0
    )
}


class PortfolioSuperStateMachine:
    """
    Portfolio-level super-state machine that coordinates all trading subsystems.
    
    This machine sits above:
    - Trading state machine (execution control)
    - Sector cap state (sector limits)
    - Portfolio state (position management)
    
    It makes high-level decisions based on market conditions and portfolio health.
    """
    
    # Valid state transitions
    VALID_TRANSITIONS = {
        PortfolioSuperState.NORMAL: [
            PortfolioSuperState.CAUTIOUS,
            PortfolioSuperState.STRESSED,
            PortfolioSuperState.EMERGENCY_HALT
        ],
        PortfolioSuperState.CAUTIOUS: [
            PortfolioSuperState.NORMAL,
            PortfolioSuperState.STRESSED,
            PortfolioSuperState.EMERGENCY_HALT
        ],
        PortfolioSuperState.STRESSED: [
            PortfolioSuperState.CAUTIOUS,
            PortfolioSuperState.CRISIS,
            PortfolioSuperState.RECOVERY,
            PortfolioSuperState.EMERGENCY_HALT
        ],
        PortfolioSuperState.CRISIS: [
            PortfolioSuperState.RECOVERY,
            PortfolioSuperState.EMERGENCY_HALT
        ],
        PortfolioSuperState.RECOVERY: [
            PortfolioSuperState.CAUTIOUS,
            PortfolioSuperState.NORMAL,
            PortfolioSuperState.STRESSED,
            PortfolioSuperState.EMERGENCY_HALT
        ],
        PortfolioSuperState.EMERGENCY_HALT: [
            PortfolioSuperState.NORMAL,  # Can only resume to normal after manual intervention
        ]
    }
    
    def __init__(
        self,
        trading_state_machine: Optional[TradingStateMachine] = None,
        sector_cap_manager: Optional[SectorCapStateManager] = None,
        portfolio_manager: Optional[PortfolioStateManager] = None,
        state_file: Optional[str] = None
    ):
        """
        Initialize portfolio super-state machine
        
        Args:
            trading_state_machine: Trading state machine instance
            sector_cap_manager: Sector cap state manager instance
            portfolio_manager: Portfolio state manager instance
            state_file: Path to state persistence file
        """
        self._lock = threading.Lock()
        
        # Initialize subsystems
        self.trading_state = trading_state_machine or get_state_machine()
        self.sector_cap = sector_cap_manager or get_sector_cap_manager()
        self.portfolio = portfolio_manager or get_portfolio_manager()
        
        # State persistence
        self._state_file = state_file or os.path.join(
            os.path.dirname(__file__),
            "..",
            ".nija_portfolio_super_state.json"
        )
        
        # Current state
        self._current_state = PortfolioSuperState.NORMAL
        self._state_history = []
        self._market_conditions = MarketConditions()
        
        # Callbacks
        self._state_callbacks: Dict[PortfolioSuperState, List[Callable]] = {
            state: [] for state in PortfolioSuperState
        }
        
        # Load persisted state
        self._load_state()
        
        logger.info("=" * 70)
        logger.info("🎯 Portfolio Super-State Machine Initialized")
        logger.info("=" * 70)
        logger.info(f"Current State: {self._current_state.value}")
        logger.info(f"Trading State: {self.trading_state.get_current_state().value}")
        logger.info(f"State File: {self._state_file}")
        logger.info("=" * 70)
    
    def _load_state(self):
        """Load persisted state from disk"""
        try:
            if os.path.exists(self._state_file):
                with open(self._state_file, 'r') as f:
                    data = json.load(f)
                
                persisted_state = PortfolioSuperState(data.get('current_state', 'normal'))
                self._state_history = data.get('history', [])
                
                # SAFETY: Start in NORMAL after restart unless in EMERGENCY_HALT
                if persisted_state == PortfolioSuperState.EMERGENCY_HALT:
                    self._current_state = PortfolioSuperState.EMERGENCY_HALT
                    logger.warning("⚠️  Resuming in EMERGENCY_HALT state")
                else:
                    self._current_state = PortfolioSuperState.NORMAL
                    logger.info(f"📂 Reset to NORMAL state (was {persisted_state.value})")
        except Exception as e:
            logger.error(f"❌ Error loading state: {e}")
            self._current_state = PortfolioSuperState.NORMAL
    
    def _persist_state(self):
        """Persist current state to disk"""
        try:
            data = {
                'current_state': self._current_state.value,
                'history': self._state_history,
                'last_updated': datetime.utcnow().isoformat(),
                'market_conditions': {
                    'volatility': self._market_conditions.current_volatility,
                    'drawdown': self._market_conditions.current_drawdown,
                    'liquidity_score': self._market_conditions.liquidity_score
                }
            }
            
            os.makedirs(os.path.dirname(self._state_file), exist_ok=True)
            
            temp_file = f"{self._state_file}.tmp"
            with open(temp_file, 'w') as f:
                json.dump(data, f, indent=2)
            os.replace(temp_file, self._state_file)
            
            logger.debug(f"💾 State persisted: {self._current_state.value}")
        except Exception as e:
            logger.error(f"❌ Error persisting state: {e}")
    
    def get_current_state(self) -> PortfolioSuperState:
        """Get current portfolio super-state"""
        with self._lock:
            return self._current_state
    
    def get_current_rules(self) -> PortfolioStateRules:
        """Get rules for current state"""
        return PORTFOLIO_STATE_RULES[self.get_current_state()]
    
    def update_market_conditions(self, conditions: MarketConditions):
        """
        Update market conditions and potentially trigger state transition
        
        Args:
            conditions: Current market conditions
        """
        with self._lock:
            self._market_conditions = conditions
            
            # Evaluate if state should change based on conditions
            recommended_state = self._evaluate_state(conditions)
            
            if recommended_state != self._current_state:
                logger.info(
                    f"📊 Market conditions suggest transition to {recommended_state.value}"
                )
                try:
                    self.transition_to(
                        recommended_state,
                        f"Market conditions: vol={conditions.current_volatility:.3f}, "
                        f"dd={conditions.current_drawdown:.3f}"
                    )
                except Exception as e:
                    logger.error(f"❌ Failed to transition: {e}")
    
    def _evaluate_state(self, conditions: MarketConditions) -> PortfolioSuperState:
        """
        Evaluate what state portfolio should be in based on conditions
        
        Args:
            conditions: Current market conditions
            
        Returns:
            Recommended portfolio state
        """
        # Emergency conditions
        if conditions.liquidity_score < 0.2 or conditions.current_drawdown > 0.50:
            return PortfolioSuperState.CRISIS
        
        # Crisis conditions
        if (conditions.current_volatility > 0.10  # 10% volatility
            or conditions.volatility_zscore > 3.0
            or conditions.current_drawdown > 0.30
            or conditions.liquidity_score < 0.4):
            return PortfolioSuperState.CRISIS
        
        # Stressed conditions
        if (conditions.current_volatility > 0.05  # 5% volatility
            or conditions.volatility_zscore > 2.0
            or conditions.current_drawdown > 0.15
            or conditions.liquidity_score < 0.6
            or conditions.sector_concentration > 25.0):
            return PortfolioSuperState.STRESSED
        
        # Recovery conditions (from crisis/stressed)
        if self._current_state in [PortfolioSuperState.CRISIS, PortfolioSuperState.STRESSED]:
            if (conditions.current_volatility < 0.04
                and conditions.current_drawdown < 0.10
                and conditions.liquidity_score > 0.7):
                return PortfolioSuperState.RECOVERY
        
        # Cautious conditions
        if (conditions.current_volatility > 0.03
            or conditions.volatility_zscore > 1.0
            or conditions.current_drawdown > 0.05
            or conditions.sector_concentration > 20.0
            or conditions.pnl_7d_pct < -5.0):
            return PortfolioSuperState.CAUTIOUS
        
        # Return to normal
        if (conditions.current_volatility < 0.03
            and conditions.current_drawdown < 0.05
            and conditions.liquidity_score > 0.8
            and conditions.sector_concentration < 20.0):
            return PortfolioSuperState.NORMAL
        
        # Default: stay in current state
        return self._current_state
    
    def transition_to(self, new_state: PortfolioSuperState, reason: str = "") -> bool:
        """
        Transition to a new portfolio state
        
        Args:
            new_state: Target state
            reason: Human-readable reason
            
        Returns:
            True if successful
        """
        with self._lock:
            current = self._current_state
            
            # Check if transition is valid
            if new_state not in self.VALID_TRANSITIONS.get(current, []):
                error_msg = (
                    f"Invalid transition: {current.value} -> {new_state.value}. "
                    f"Allowed: {[s.value for s in self.VALID_TRANSITIONS.get(current, [])]}"
                )
                logger.error(f"❌ {error_msg}")
                return False
            
            # Record transition
            transition_record = {
                'from': current.value,
                'to': new_state.value,
                'reason': reason,
                'timestamp': datetime.utcnow().isoformat(),
                'market_conditions': {
                    'volatility': self._market_conditions.current_volatility,
                    'drawdown': self._market_conditions.current_drawdown,
                    'liquidity': self._market_conditions.liquidity_score
                }
            }
            self._state_history.append(transition_record)
            
            # Update state
            old_state = self._current_state
            self._current_state = new_state
            
            # Persist
            self._persist_state()
            
            # Log transition
            logger.info("=" * 70)
            logger.info(
                f"🔄 Portfolio State Transition: {old_state.value} -> {new_state.value}"
            )
            logger.info(f"Reason: {reason or 'No reason provided'}")
            logger.info("=" * 70)
            
            # Apply state rules
            self._apply_state_rules(new_state)
            
            # Trigger callbacks
            self._trigger_callbacks(new_state)
            
            return True
    
    def _apply_state_rules(self, state: PortfolioSuperState):
        """Apply rules for the new state"""
        rules = PORTFOLIO_STATE_RULES[state]
        
        logger.info("📋 Applying Portfolio State Rules:")
        logger.info(f"  Max Position Size: {rules.max_position_size_pct}%")
        logger.info(f"  Max Portfolio Utilization: {rules.max_portfolio_utilization_pct}%")
        logger.info(f"  Max Sector Exposure: {rules.max_sector_exposure_pct}%")
        logger.info(f"  Min Cash Reserve: {rules.min_cash_reserve_pct}%")
        logger.info(f"  Max Positions: {rules.max_concurrent_positions}")
        logger.info(f"  New Positions Allowed: {rules.allow_new_positions}")
        logger.info(f"  Risk Multiplier: {rules.risk_multiplier}x")
        
        # Update sector cap limits
        sector_state = self.sector_cap.get_state()
        sector_state.global_hard_limit_pct = rules.max_sector_exposure_pct
        sector_state.global_soft_limit_pct = rules.max_sector_exposure_pct * 0.75
        
        # If force reduction, log warning
        if rules.force_position_reduction:
            logger.warning("⚠️  POSITION REDUCTION REQUIRED")
    
    def can_open_new_position(
        self,
        symbol: str,
        position_value: float,
        portfolio_value: float
    ) -> Tuple[bool, str]:
        """
        Check if a new position can be opened given current super-state
        
        Args:
            symbol: Trading symbol
            position_value: Position value in USD
            portfolio_value: Total portfolio value
            
        Returns:
            Tuple of (can_open, reason)
        """
        rules = self.get_current_rules()
        
        # Check if new positions are allowed
        if not rules.allow_new_positions:
            return False, f"New positions not allowed in {self._current_state.value} state"
        
        # Check trading state machine
        if not self.trading_state.is_trading_allowed():
            return False, "Trading not allowed by trading state machine"
        
        # Check position size limit
        position_size_pct = (position_value / portfolio_value * 100) if portfolio_value > 0 else 0
        if position_size_pct > rules.max_position_size_pct:
            return False, f"Position size ({position_size_pct:.1f}%) exceeds limit ({rules.max_position_size_pct}%)"
        
        # Check sector limits
        can_add, reason = self.sector_cap.get_state().can_add_position(symbol, position_value)
        if not can_add:
            return False, f"Sector limit: {reason}"
        
        return True, "OK"
    
    def register_callback(self, state: PortfolioSuperState, callback: Callable):
        """Register callback for state entry"""
        with self._lock:
            self._state_callbacks[state].append(callback)
            logger.debug(f"📌 Registered callback for {state.value}")
    
    def _trigger_callbacks(self, state: PortfolioSuperState):
        """Trigger callbacks for state"""
        callbacks = self._state_callbacks.get(state, [])
        for callback in callbacks:
            try:
                callback()
            except Exception as e:
                logger.error(f"❌ Error in callback: {e}")
    
    def get_summary(self) -> Dict[str, Any]:
        """Get comprehensive summary"""
        rules = self.get_current_rules()
        
        return {
            'current_state': self._current_state.value,
            'trading_state': self.trading_state.get_current_state().value,
            'market_conditions': {
                'volatility': self._market_conditions.current_volatility,
                'drawdown': self._market_conditions.current_drawdown,
                'liquidity_score': self._market_conditions.liquidity_score,
                'sector_concentration': self._market_conditions.sector_concentration
            },
            'current_rules': {
                'max_position_size_pct': rules.max_position_size_pct,
                'max_portfolio_utilization_pct': rules.max_portfolio_utilization_pct,
                'max_sector_exposure_pct': rules.max_sector_exposure_pct,
                'allow_new_positions': rules.allow_new_positions,
                'risk_multiplier': rules.risk_multiplier
            },
            'recent_history': self._state_history[-5:] if self._state_history else []
        }


# Global singleton
_super_state_machine: Optional[PortfolioSuperStateMachine] = None
_instance_lock = threading.Lock()


def get_portfolio_super_state_machine() -> PortfolioSuperStateMachine:
    """Get global portfolio super-state machine instance"""
    global _super_state_machine
    
    if _super_state_machine is None:
        with _instance_lock:
            if _super_state_machine is None:
                _super_state_machine = PortfolioSuperStateMachine()
    
    return _super_state_machine


# Example usage
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    # Create super-state machine
    ssm = get_portfolio_super_state_machine()
    
    print("\n=== Portfolio Super-State Machine Test ===")
    print(f"Current State: {ssm.get_current_state().value}")
    
    # Simulate normal conditions
    normal_conditions = MarketConditions(
        current_volatility=0.02,
        current_drawdown=0.03,
        liquidity_score=0.9
    )
    ssm.update_market_conditions(normal_conditions)
    
    # Simulate crisis conditions
    print("\n--- Simulating Crisis Conditions ---")
    crisis_conditions = MarketConditions(
        current_volatility=0.12,
        current_drawdown=0.35,
        liquidity_score=0.3
    )
    ssm.update_market_conditions(crisis_conditions)
    print(f"State after crisis: {ssm.get_current_state().value}")
    
    # Check if can open position
    can_open, reason = ssm.can_open_new_position("BTC-USD", 1000, 10000)
    print(f"\nCan open position in crisis? {can_open} - {reason}")
    
    # Get summary
    summary = ssm.get_summary()
    print("\n--- Summary ---")
    print(f"State: {summary['current_state']}")
    print(f"Rules: {summary['current_rules']}")
