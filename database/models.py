"""
NIJA Database Models

SQLAlchemy ORM models for the NIJA trading platform.

Author: NIJA Trading Systems
Version: 1.0
Date: January 27, 2026
"""

from datetime import datetime
from typing import Optional
from sqlalchemy import Column, Integer, String, Numeric, Boolean, DateTime, Date, ForeignKey, Text
from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy.sql import func

Base = declarative_base()


class User(Base):
    """User account model"""
    __tablename__ = 'users'

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(50), unique=True, nullable=False, index=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    subscription_tier = Column(String(20), default='basic')
    enabled = Column(Boolean, default=True)
    education_mode = Column(Boolean, default=True)  # Start in education mode by default
    consented_to_live_trading = Column(Boolean, default=False)  # Explicit consent required
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # Relationships
    broker_credentials = relationship("BrokerCredential", back_populates="user", cascade="all, delete-orphan")
    permissions = relationship("UserPermission", back_populates="user", uselist=False, cascade="all, delete-orphan")
    trading_instance = relationship("TradingInstance", back_populates="user", uselist=False, cascade="all, delete-orphan")
    positions = relationship("Position", back_populates="user", cascade="all, delete-orphan")
    trades = relationship("Trade", back_populates="user", cascade="all, delete-orphan")
    daily_stats = relationship("DailyStatistic", back_populates="user", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<User(user_id='{self.user_id}', email='{self.email}', tier='{self.subscription_tier}')>"


class BrokerCredential(Base):
    """Broker API credentials (encrypted)"""
    __tablename__ = 'broker_credentials'

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(50), ForeignKey('users.user_id', ondelete='CASCADE'), nullable=False, index=True)
    broker_name = Column(String(50), nullable=False)
    encrypted_api_key = Column(Text, nullable=False)
    encrypted_api_secret = Column(Text, nullable=False)
    encrypted_additional_params = Column(Text)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # Relationships
    user = relationship("User", back_populates="broker_credentials")

    def __repr__(self):
        return f"<BrokerCredential(user_id='{self.user_id}', broker='{self.broker_name}')>"


class UserPermission(Base):
    """User trading permissions and limits"""
    __tablename__ = 'user_permissions'

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(50), ForeignKey('users.user_id', ondelete='CASCADE'), unique=True, nullable=False)
    max_position_size_usd = Column(Numeric(12, 2), default=100.00)
    max_daily_loss_usd = Column(Numeric(12, 2), default=50.00)
    max_positions = Column(Integer, default=3)
    trade_only = Column(Boolean, default=True)
    enabled = Column(Boolean, default=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # Relationships
    user = relationship("User", back_populates="permissions")

    def __repr__(self):
        return f"<UserPermission(user_id='{self.user_id}', max_positions={self.max_positions})>"


class TradingInstance(Base):
    """Trading bot instance for each user"""
    __tablename__ = 'trading_instances'

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(50), ForeignKey('users.user_id', ondelete='CASCADE'), unique=True, nullable=False)
    status = Column(String(20), default='stopped')
    container_id = Column(String(255))
    started_at = Column(DateTime)
    stopped_at = Column(DateTime)
    last_activity = Column(DateTime)
    created_at = Column(DateTime, default=func.now())

    # Relationships
    user = relationship("User", back_populates="trading_instance")

    def __repr__(self):
        return f"<TradingInstance(user_id='{self.user_id}', status='{self.status}')>"


class Position(Base):
    """Active trading positions"""
    __tablename__ = 'positions'

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(50), ForeignKey('users.user_id', ondelete='CASCADE'), nullable=False, index=True)
    pair = Column(String(20), nullable=False)
    side = Column(String(10), nullable=False)
    size = Column(Numeric(18, 8), nullable=False)
    entry_price = Column(Numeric(18, 8), nullable=False)
    current_price = Column(Numeric(18, 8))
    pnl = Column(Numeric(18, 8))
    pnl_percent = Column(Numeric(8, 4))
    opened_at = Column(DateTime, default=func.now())
    closed_at = Column(DateTime)
    status = Column(String(20), default='open', index=True)

    # Relationships
    user = relationship("User", back_populates="positions")

    def __repr__(self):
        return f"<Position(user_id='{self.user_id}', pair='{self.pair}', size={self.size}, status='{self.status}')>"


class Trade(Base):
    """Trade history"""
    __tablename__ = 'trades'

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(50), ForeignKey('users.user_id', ondelete='CASCADE'), nullable=False, index=True)
    pair = Column(String(20), nullable=False)
    side = Column(String(10), nullable=False)
    size = Column(Numeric(18, 8), nullable=False)
    entry_price = Column(Numeric(18, 8), nullable=False)
    exit_price = Column(Numeric(18, 8))
    pnl = Column(Numeric(18, 8))
    pnl_percent = Column(Numeric(8, 4))
    fees = Column(Numeric(18, 8))
    opened_at = Column(DateTime, default=func.now())
    closed_at = Column(DateTime, index=True)
    status = Column(String(20), default='open')

    # Relationships
    user = relationship("User", back_populates="trades")

    def __repr__(self):
        return f"<Trade(user_id='{self.user_id}', pair='{self.pair}', pnl={self.pnl})>"


class DailyStatistic(Base):
    """Daily aggregated statistics per user"""
    __tablename__ = 'daily_statistics'

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(50), ForeignKey('users.user_id', ondelete='CASCADE'), nullable=False)
    date = Column(Date, nullable=False)
    total_trades = Column(Integer, default=0)
    winning_trades = Column(Integer, default=0)
    losing_trades = Column(Integer, default=0)
    total_pnl = Column(Numeric(18, 8), default=0)
    total_fees = Column(Numeric(18, 8), default=0)
    created_at = Column(DateTime, default=func.now())

    # Relationships
    user = relationship("User", back_populates="daily_stats")

    def __repr__(self):
        return f"<DailyStatistic(user_id='{self.user_id}', date={self.date}, total_pnl={self.total_pnl})>"


class PerformanceSnapshot(Base):
    """Performance snapshot for NAV and equity tracking"""
    __tablename__ = 'performance_snapshots'

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(50), ForeignKey('users.user_id', ondelete='CASCADE'), nullable=False, index=True)
    timestamp = Column(DateTime, nullable=False, default=func.now(), index=True)

    # NAV and equity
    nav = Column(Numeric(18, 8), nullable=False)
    equity = Column(Numeric(18, 8), nullable=False)
    cash = Column(Numeric(18, 8), nullable=False)
    positions_value = Column(Numeric(18, 8), default=0)
    unrealized_pnl = Column(Numeric(18, 8), default=0)
    realized_pnl_today = Column(Numeric(18, 8), default=0)

    # Trade counts
    total_trades = Column(Integer, default=0)
    winning_trades = Column(Integer, default=0)
    losing_trades = Column(Integer, default=0)

    # Performance metrics
    daily_return_pct = Column(Numeric(8, 4), default=0)
    sharpe_ratio = Column(Numeric(8, 4), default=0)
    max_drawdown_pct = Column(Numeric(8, 4), default=0)
    current_drawdown_pct = Column(Numeric(8, 4), default=0)

    created_at = Column(DateTime, default=func.now())

    def __repr__(self):
        return f"<PerformanceSnapshot(user_id='{self.user_id}', timestamp={self.timestamp}, nav={self.nav})>"


class StrategyPerformance(Base):
    """Track performance of individual trading strategies"""
    __tablename__ = 'strategy_performance'

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(50), ForeignKey('users.user_id', ondelete='CASCADE'), nullable=False, index=True)
    strategy_name = Column(String(50), nullable=False, index=True)

    # Performance metrics
    total_trades = Column(Integer, default=0)
    winning_trades = Column(Integer, default=0)
    losing_trades = Column(Integer, default=0)
    total_pnl = Column(Numeric(18, 8), default=0)
    sharpe_ratio = Column(Numeric(8, 4), default=0)
    max_drawdown_pct = Column(Numeric(8, 4), default=0)

    # Allocation
    current_allocation_pct = Column(Numeric(8, 4), default=0)

    # Timestamps
    last_updated = Column(DateTime, default=func.now(), onupdate=func.now())
    created_at = Column(DateTime, default=func.now())

    def __repr__(self):
        return f"<StrategyPerformance(user_id='{self.user_id}', strategy='{self.strategy_name}', pnl={self.total_pnl})>"


class MonthlyReport(Base):
    """Monthly performance reports"""
    __tablename__ = 'monthly_reports'

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(50), ForeignKey('users.user_id', ondelete='CASCADE'), nullable=False, index=True)
    year = Column(Integer, nullable=False, index=True)
    month = Column(Integer, nullable=False, index=True)

    # NAV and returns
    start_nav = Column(Numeric(18, 8), nullable=False)
    end_nav = Column(Numeric(18, 8), nullable=False)
    monthly_return_pct = Column(Numeric(8, 4), default=0)

    # Trading metrics
    total_trades = Column(Integer, default=0)
    winning_trades = Column(Integer, default=0)
    losing_trades = Column(Integer, default=0)
    win_rate_pct = Column(Numeric(8, 4), default=0)

    # Risk metrics
    max_drawdown_pct = Column(Numeric(8, 4), default=0)
    sharpe_ratio = Column(Numeric(8, 4), default=0)
    volatility_pct = Column(Numeric(8, 4), default=0)

    # Activity
    trading_days = Column(Integer, default=0)
    avg_trades_per_day = Column(Numeric(8, 4), default=0)

    created_at = Column(DateTime, default=func.now())

    def __repr__(self):
        return f"<MonthlyReport(user_id='{self.user_id}', year={self.year}, month={self.month}, return={self.monthly_return_pct}%)>"


class PortfolioEquity(Base):
    """Portfolio equity tracking with regime and volatility"""
    __tablename__ = 'portfolio_equity'

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(50), ForeignKey('users.user_id', ondelete='CASCADE'), nullable=False, index=True)
    timestamp = Column(DateTime, nullable=False, default=func.now(), index=True)

    # Core metrics
    equity = Column(Numeric(18, 8), nullable=False)
    drawdown_pct = Column(Numeric(8, 4), default=0)
    volatility_pct = Column(Numeric(8, 4), default=0)
    regime = Column(String(20), default='neutral')  # bull_trending, bear_trending, ranging, volatile, crisis

    created_at = Column(DateTime, default=func.now())

    def __repr__(self):
        return f"<PortfolioEquity(user_id='{self.user_id}', timestamp={self.timestamp}, equity={self.equity}, regime='{self.regime}')>"


class DailyReturn(Base):
    """Daily return tracking"""
    __tablename__ = 'daily_returns'

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(50), ForeignKey('users.user_id', ondelete='CASCADE'), nullable=False, index=True)
    date = Column(Date, nullable=False, index=True)
    return_pct = Column(Numeric(8, 4), nullable=False)

    created_at = Column(DateTime, default=func.now())

    def __repr__(self):
        return f"<DailyReturn(user_id='{self.user_id}', date={self.date}, return={self.return_pct}%)>"


class RiskEvent(Base):
    """Risk events log"""
    __tablename__ = 'risk_events'

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(50), ForeignKey('users.user_id', ondelete='CASCADE'), nullable=False, index=True)
    timestamp = Column(DateTime, nullable=False, default=func.now(), index=True)

    # Event details
    event_type = Column(String(50), nullable=False)  # drawdown_warning, volatility_spike, regime_change, etc.
    severity = Column(String(20), default='info')  # info, warning, critical
    description = Column(Text)

    # Metrics at time of event
    equity = Column(Numeric(18, 8))
    drawdown_pct = Column(Numeric(8, 4))
    volatility_pct = Column(Numeric(8, 4))

    created_at = Column(DateTime, default=func.now())

    def __repr__(self):
        return f"<RiskEvent(user_id='{self.user_id}', type='{self.event_type}', severity='{self.severity}')>"
