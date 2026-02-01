"""
NIJA Portfolio State Manager
============================

Portfolio-first accounting system that tracks total equity instead of just available cash.

CRITICAL FIX (Problem Statement):
NIJA must stop using available cash as its truth. All logic must use TOTAL_EQUITY.

TOTAL_EQUITY = available_cash + sum(open_position_market_value) + unrealized_pnl

This ensures accurate risk calculations and position sizing that accounts for capital
already deployed in open positions.
"""

import logging
from typing import Dict, List, Optional
from dataclasses import dataclass, field
from datetime import datetime

logger = logging.getLogger("nija.portfolio")


@dataclass
class Position:
    """Represents an open trading position."""
    symbol: str
    quantity: float
    entry_price: float
    current_price: float
    market_value: float  # current_price * quantity
    unrealized_pnl: float  # (current_price - entry_price) * quantity
    unrealized_pnl_pct: float  # unrealized_pnl / (entry_price * quantity)
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())

    def update_price(self, new_price: float):
        """Update current price and recalculate derived values."""
        self.current_price = new_price
        self.market_value = new_price * self.quantity
        self.unrealized_pnl = (new_price - self.entry_price) * self.quantity
        cost_basis = self.entry_price * self.quantity
        self.unrealized_pnl_pct = (self.unrealized_pnl / cost_basis * 100) if cost_basis > 0 else 0.0


@dataclass
class PortfolioState:
    """
    Portfolio state using TOTAL EQUITY as source of truth.

    This is the MANDATORY accounting model for NIJA.
    All trading logic must use total_equity, not available_cash.
    """
    available_cash: float
    open_positions: Dict[str, Position] = field(default_factory=dict)
    min_reserve_pct: float = 0.10  # Minimum 10% reserve to keep as cash

    @property
    def total_position_value(self) -> float:
        """Sum of all open position market values."""
        return sum(pos.market_value for pos in self.open_positions.values())

    @property
    def unrealized_pnl(self) -> float:
        """Sum of all unrealized profit/loss from open positions."""
        return sum(pos.unrealized_pnl for pos in self.open_positions.values())

    @property
    def total_equity(self) -> float:
        """
        TOTAL EQUITY = available_cash + position_value + unrealized_pnl

        This is the TRUE portfolio value and must be used for all risk calculations.

        Note: position_value already includes unrealized_pnl in market value,
        so we don't double-count: total_equity = cash + position_market_value
        """
        return self.available_cash + self.total_position_value

    @property
    def position_count(self) -> int:
        """Number of open positions."""
        return len(self.open_positions)

    @property
    def cash_utilization_pct(self) -> float:
        """Percentage of total equity currently in positions."""
        if self.total_equity <= 0:
            return 0.0
        return (self.total_position_value / self.total_equity) * 100

    def calculate_deployable_capital(self, min_reserve_pct: Optional[float] = None) -> float:
        """
        Calculate effective deployable capital.

        This is the maximum amount of capital that can be deployed in new positions,
        accounting for:
        - Total equity (cash + positions)
        - Minimum cash reserve requirements
        - Capital already deployed in open positions

        Formula:
            deployable_capital = total_equity * (1 - min_reserve_pct) - total_position_value

        Args:
            min_reserve_pct: Minimum percentage of total equity to keep as reserve (default: self.min_reserve_pct)

        Returns:
            float: Amount of capital available for deployment in USD
        """
        if min_reserve_pct is None:
            min_reserve_pct = self.min_reserve_pct

        # Calculate minimum reserve that must be maintained
        min_reserve_amount = self.total_equity * min_reserve_pct

        # Maximum deployable is total equity minus reserve requirement
        max_deployable = self.total_equity - min_reserve_amount

        # Subtract what's already deployed in positions
        effective_deployable = max_deployable - self.total_position_value

        # Cannot deploy more than available cash
        effective_deployable = min(effective_deployable, self.available_cash)

        # Cannot be negative
        effective_deployable = max(0.0, effective_deployable)

        return effective_deployable

    def calculate_max_position_size(
        self,
        max_position_pct: float = 0.15,
        min_reserve_pct: Optional[float] = None
    ) -> float:
        """
        Calculate maximum position size for a single trade.

        This accounts for:
        - Total equity (not just available cash)
        - Maximum position size as percentage of total equity
        - Minimum reserve requirements
        - Available deployable capital

        Args:
            max_position_pct: Maximum position size as % of total equity (default: 0.15 = 15%)
            min_reserve_pct: Minimum percentage of total equity to keep as reserve (default: self.min_reserve_pct)

        Returns:
            float: Maximum position size in USD
        """
        if min_reserve_pct is None:
            min_reserve_pct = self.min_reserve_pct

        # Calculate max based on percentage of total equity
        max_by_percentage = self.total_equity * max_position_pct

        # Calculate effective deployable capital
        deployable = self.calculate_deployable_capital(min_reserve_pct)

        # Take the minimum of the two (most conservative)
        max_position = min(max_by_percentage, deployable)

        # Cannot exceed available cash
        max_position = min(max_position, self.available_cash)

        # Cannot be negative
        max_position = max(0.0, max_position)

        return max_position

    def add_position(self, symbol: str, quantity: float, entry_price: float, current_price: Optional[float] = None):
        """
        Add or update an open position.

        Args:
            symbol: Trading pair symbol
            quantity: Position size in base currency
            entry_price: Entry price per unit
            current_price: Current market price (defaults to entry_price if not provided)
        """
        if current_price is None:
            current_price = entry_price

        market_value = current_price * quantity
        unrealized_pnl = (current_price - entry_price) * quantity
        cost_basis = entry_price * quantity
        unrealized_pnl_pct = (unrealized_pnl / cost_basis * 100) if cost_basis > 0 else 0.0

        self.open_positions[symbol] = Position(
            symbol=symbol,
            quantity=quantity,
            entry_price=entry_price,
            current_price=current_price,
            market_value=market_value,
            unrealized_pnl=unrealized_pnl,
            unrealized_pnl_pct=unrealized_pnl_pct
        )

        logger.debug(f"Added position: {symbol} qty={quantity:.8f} @ ${entry_price:.2f}")

    def update_position_price(self, symbol: str, new_price: float):
        """
        Update the current price for a position.

        Args:
            symbol: Trading pair symbol
            new_price: New market price
        """
        if symbol in self.open_positions:
            self.open_positions[symbol].update_price(new_price)
            logger.debug(f"Updated {symbol} price: ${new_price:.2f}")

    def remove_position(self, symbol: str):
        """
        Remove a closed position.

        Args:
            symbol: Trading pair symbol
        """
        if symbol in self.open_positions:
            del self.open_positions[symbol]
            logger.debug(f"Removed position: {symbol}")

    def update_cash(self, new_cash: float):
        """
        Update available cash balance.

        Args:
            new_cash: New available cash amount
        """
        self.available_cash = new_cash

    def get_summary(self) -> Dict:
        """Get a summary of the portfolio state."""
        return {
            'available_cash': self.available_cash,
            'total_position_value': self.total_position_value,
            'unrealized_pnl': self.unrealized_pnl,
            'total_equity': self.total_equity,
            'position_count': self.position_count,
            'cash_utilization_pct': self.cash_utilization_pct,
            'deployable_capital': self.calculate_deployable_capital(),
            'max_position_size': self.calculate_max_position_size(),
            'positions': {
                symbol: {
                    'quantity': pos.quantity,
                    'entry_price': pos.entry_price,
                    'current_price': pos.current_price,
                    'market_value': pos.market_value,
                    'unrealized_pnl': pos.unrealized_pnl,
                    'unrealized_pnl_pct': pos.unrealized_pnl_pct
                }
                for symbol, pos in self.open_positions.items()
            }
        }

    def get_capital_breakdown(
        self,
        max_position_pct: float = 0.15,
        min_reserve_pct: Optional[float] = None
    ) -> Dict:
        """
        Get detailed breakdown of capital allocation and capacity.

        This provides a comprehensive view of:
        - How much capital is currently deployed
        - How much is available for deployment
        - What the maximum position size can be
        - Reserve requirements

        Args:
            max_position_pct: Maximum position size as % of total equity
            min_reserve_pct: Minimum reserve percentage (default: self.min_reserve_pct)

        Returns:
            Dict with detailed capital breakdown
        """
        if min_reserve_pct is None:
            min_reserve_pct = self.min_reserve_pct

        deployable = self.calculate_deployable_capital(min_reserve_pct)
        max_position = self.calculate_max_position_size(max_position_pct, min_reserve_pct)
        min_reserve_amount = self.total_equity * min_reserve_pct
        max_deployable_total = self.total_equity - min_reserve_amount

        return {
            # Core balances
            'total_equity': self.total_equity,
            'available_cash': self.available_cash,
            'total_position_value': self.total_position_value,
            'unrealized_pnl': self.unrealized_pnl,

            # Position metrics
            'position_count': self.position_count,
            'cash_utilization_pct': self.cash_utilization_pct,

            # Capital deployment
            'min_reserve_pct': min_reserve_pct * 100,  # As percentage
            'min_reserve_amount': min_reserve_amount,
            'max_deployable_total': max_deployable_total,
            'current_deployed': self.total_position_value,
            'deployable_capital': deployable,

            # Position sizing
            'max_position_pct': max_position_pct * 100,  # As percentage
            'max_position_size': max_position,

            # Capacity metrics
            'deployment_capacity_used_pct': (self.total_position_value / max_deployable_total * 100) if max_deployable_total > 0 else 0,
            'remaining_capacity': max_deployable_total - self.total_position_value if max_deployable_total > self.total_position_value else 0
        }


@dataclass
class UserPortfolioState(PortfolioState):
    """
    Portfolio state for a user account.

    Each user must have their own portfolio state that is independent
    from the platform account and other users.

    FIX #3: USER ACCOUNTS MUST HAVE THEIR OWN PORTFOLIO STATE
    """
    user_id: str = ""
    broker_type: str = ""

    def __post_init__(self):
        """Initialize user-specific fields."""
        if not self.user_id:
            logger.warning("UserPortfolioState created without user_id")


class PortfolioStateManager:
    """
    Manages portfolio states for master and all user accounts.

    Ensures each account has its own isolated portfolio state for
    accurate risk management and position sizing.
    """

    def __init__(self):
        """Initialize the portfolio state manager."""
        self.platform_portfolio: Optional[PortfolioState] = None
        self.user_portfolios: Dict[str, UserPortfolioState] = {}
        logger.info("PortfolioStateManager initialized")

    def initialize_platform_portfolio(self, available_cash: float) -> PortfolioState:
        """
        Initialize or update master portfolio.

        CRITICAL FIX (Jan 22, 2026): Prevent overwriting existing master portfolio.
        Only updates cash balance if portfolio already exists.

        Args:
            available_cash: Available cash in platform account (should be sum of ALL master brokers)

        Returns:
            PortfolioState: Master portfolio state
        """
        if self.platform_portfolio is None:
            self.platform_portfolio = PortfolioState(available_cash=available_cash)
            logger.info(f"Master portfolio initialized with ${available_cash:.2f}")
        else:
            # Portfolio already exists - only update cash balance, preserve positions
            old_cash = self.platform_portfolio.available_cash
            self.platform_portfolio.update_cash(available_cash)
            logger.debug(f"Master portfolio cash updated: ${old_cash:.2f} → ${available_cash:.2f}")
        return self.platform_portfolio

    def initialize_user_portfolio(self, user_id: str, broker_type: str, available_cash: float) -> UserPortfolioState:
        """
        Initialize or update user portfolio.

        Args:
            user_id: User identifier
            broker_type: Broker type (coinbase, kraken, alpaca, etc.)
            available_cash: Available cash in user account

        Returns:
            UserPortfolioState: User portfolio state
        """
        portfolio_key = f"{user_id}_{broker_type}"

        if portfolio_key not in self.user_portfolios:
            self.user_portfolios[portfolio_key] = UserPortfolioState(
                available_cash=available_cash,
                user_id=user_id,
                broker_type=broker_type
            )
            logger.info(f"User portfolio initialized: {user_id} ({broker_type}) with ${available_cash:.2f}")
        else:
            self.user_portfolios[portfolio_key].update_cash(available_cash)

        return self.user_portfolios[portfolio_key]

    def get_platform_portfolio(self) -> Optional[PortfolioState]:
        """Get master portfolio state."""
        return self.platform_portfolio

    def get_user_portfolio(self, user_id: str, broker_type: str) -> Optional[UserPortfolioState]:
        """
        Get user portfolio state.

        Args:
            user_id: User identifier
            broker_type: Broker type

        Returns:
            UserPortfolioState or None if not found
        """
        portfolio_key = f"{user_id}_{broker_type}"
        return self.user_portfolios.get(portfolio_key)

    def update_portfolio_from_broker(
        self,
        portfolio: PortfolioState,
        available_cash: float,
        positions: List[Dict]
    ):
        """
        Update a portfolio state from broker data.

        Args:
            portfolio: Portfolio state to update
            available_cash: Current available cash from broker
            positions: List of position dicts from broker
        """
        # Update cash
        portfolio.update_cash(available_cash)

        # Clear and rebuild positions
        portfolio.open_positions.clear()

        for pos_dict in positions:
            symbol = pos_dict.get('symbol')
            quantity = pos_dict.get('quantity', 0.0)

            # Try to get entry price from position data
            entry_price = pos_dict.get('entry_price') or pos_dict.get('avg_entry_price')
            current_price = pos_dict.get('current_price') or pos_dict.get('market_price')

            # If we don't have entry price, use current price as fallback
            if not entry_price:
                entry_price = current_price if current_price else 0.0

            if symbol and quantity > 0 and entry_price > 0:
                portfolio.add_position(
                    symbol=symbol,
                    quantity=quantity,
                    entry_price=entry_price,
                    current_price=current_price
                )

        logger.debug(f"Portfolio updated: {portfolio.position_count} positions, equity=${portfolio.total_equity:.2f}")


# Global instance for easy access
_portfolio_manager: Optional[PortfolioStateManager] = None


def get_portfolio_manager() -> PortfolioStateManager:
    """Get or create the global portfolio state manager."""
    global _portfolio_manager
    if _portfolio_manager is None:
        _portfolio_manager = PortfolioStateManager()
    return _portfolio_manager
