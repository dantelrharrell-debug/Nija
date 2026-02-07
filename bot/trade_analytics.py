"""
NIJA Trade Analytics Module
============================

Comprehensive analytics for trading operations covering:
1. PnL Attribution (per strategy / per signal)
2. Trade Outcome Reason Codes (entry/exit reasons)
3. Market Scan Timing Metrics (verify 732 markets scanned in time)
4. Capital Utilization Reports (idle vs active capital)

This module tracks fees, performance metrics, and generates detailed reports.

Author: NIJA Trading Systems
Enhanced: February 7, 2026
"""

import json
import logging
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict, field
from collections import defaultdict
from enum import Enum
import threading

logger = logging.getLogger("nija.analytics")


# ============================================================================
# TRADE OUTCOME REASON CODES (Requirement #2)
# ============================================================================

class EntryReason(Enum):
    """Standardized entry reason codes"""
    # RSI-based entries
    RSI_9_OVERSOLD = "rsi_9_oversold"
    RSI_14_OVERSOLD = "rsi_14_oversold"
    DUAL_RSI_OVERSOLD = "dual_rsi_oversold"
    RSI_DIVERGENCE = "rsi_divergence"
    
    # TradingView signals
    TRADINGVIEW_BUY_SIGNAL = "tradingview_buy_signal"
    TRADINGVIEW_SELL_SIGNAL = "tradingview_sell_signal"
    
    # Market conditions
    MARKET_READINESS_PASSED = "market_readiness_passed"
    STRONG_MOMENTUM = "strong_momentum"
    
    # Other
    MANUAL_ENTRY = "manual_entry"
    HEARTBEAT_TRADE = "heartbeat_trade"
    UNKNOWN = "unknown"


class ExitReason(Enum):
    """Standardized exit reason codes"""
    # Profit targets
    PROFIT_TARGET_1 = "profit_target_1"
    PROFIT_TARGET_2 = "profit_target_2"
    PROFIT_TARGET_3 = "profit_target_3"
    FULL_PROFIT_TARGET = "full_profit_target"
    TRAILING_STOP_HIT = "trailing_stop_hit"
    
    # Stop losses
    STOP_LOSS_HIT = "stop_loss_hit"
    TIME_BASED_STOP = "time_based_stop"
    LOSING_TRADE_EXIT = "losing_trade_exit"
    
    # RSI-based exits
    RSI_OVERBOUGHT = "rsi_overbought"
    RSI_OVERSOLD_EXIT = "rsi_oversold_exit"
    
    # Risk management
    DAILY_LOSS_LIMIT = "daily_loss_limit"
    POSITION_LIMIT_ENFORCEMENT = "position_limit_enforcement"
    KILL_SWITCH = "kill_switch"
    LIQUIDATE_ALL = "liquidate_all"
    
    # Position management
    DUST_POSITION = "dust_position"
    ZOMBIE_POSITION = "zombie_position"
    ADOPTION_EXIT = "adoption_exit"
    
    # Manual
    MANUAL_EXIT = "manual_exit"
    UNKNOWN = "unknown"


class SignalType(Enum):
    """Trading signal types for PnL attribution"""
    RSI_9_ONLY = "rsi_9_only"
    RSI_14_ONLY = "rsi_14_only"
    DUAL_RSI = "dual_rsi"
    TRADINGVIEW = "tradingview"
    HEARTBEAT = "heartbeat"
    MANUAL = "manual"
    UNKNOWN = "unknown"


@dataclass
class TradeRecord:
    """Single trade record with all details"""
    timestamp: str
    symbol: str
    side: str  # BUY or SELL
    entry_price: float
    exit_price: Optional[float] = None
    size_usd: float = 0.0
    quantity: float = 0.0

    # Fees
    entry_fee: float = 0.0
    exit_fee: float = 0.0
    total_fees: float = 0.0

    # Performance
    gross_profit: float = 0.0  # Before fees
    net_profit: float = 0.0    # After fees
    profit_pct: float = 0.0

    # Execution details
    expected_price: float = 0.0
    actual_fill_price: float = 0.0
    slippage: float = 0.0
    slippage_pct: float = 0.0

    # Risk management
    stop_loss: float = 0.0
    take_profit: float = 0.0
    exit_reason: str = ""

    # Trade duration
    entry_time: str = ""
    exit_time: Optional[str] = None
    duration_seconds: float = 0.0
    
    # ENHANCED: Reason codes and attribution (Requirement #1 & #2)
    entry_reason: str = "unknown"  # EntryReason value
    entry_signal_type: str = "unknown"  # SignalType value
    strategy_name: str = "apex_v71"  # Strategy attribution
    rsi_9_value: Optional[float] = None
    rsi_14_value: Optional[float] = None
    broker: str = "coinbase"
    trade_id: str = ""


@dataclass
class MarketScanMetrics:
    """Metrics for a single market scan cycle (Requirement #3)"""
    scan_id: str
    timestamp_start: str
    timestamp_end: str
    duration_seconds: float
    
    # Markets
    total_markets_available: int
    markets_scanned: int
    markets_skipped: int
    
    # Timing breakdown
    avg_time_per_market_ms: float
    total_api_calls: int
    total_rate_limit_delays_ms: float
    
    # Outcomes
    signals_generated: int
    trades_executed: int
    
    # Batch info
    batch_size: int
    batch_number: int
    rotation_enabled: bool


@dataclass
class CapitalUtilization:
    """Capital utilization snapshot (Requirement #4)"""
    timestamp: str
    
    # Total capital
    total_capital_usd: float
    
    # Capital allocation
    capital_in_positions_usd: float
    idle_capital_usd: float
    
    # Metrics
    utilization_pct: float
    num_positions: int
    avg_position_size_usd: float
    
    # Position details
    largest_position_usd: float
    smallest_position_usd: float
    largest_position_symbol: str
    
    # Performance context
    unrealized_pnl_usd: float
    realized_pnl_today_usd: float


class TradeAnalytics:
    """
    Comprehensive trade analytics and performance tracking
    
    Enhanced with:
    1. PnL Attribution (per strategy / per signal)
    2. Trade Outcome Reason Codes (entry/exit reasons)
    3. Market Scan Timing Metrics
    4. Capital Utilization Reports
    """

    # Coinbase Advanced Trade fee tier (default: taker)
    COINBASE_TAKER_FEE = 0.006  # 0.6%
    COINBASE_MAKER_FEE = 0.004  # 0.4%

    def __init__(self, data_dir: str = "./data"):
        """
        Initialize analytics tracker

        Args:
            data_dir: Directory to store trade history and reports
        """
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(exist_ok=True, parents=True)

        # Create analytics subdirectory
        self.analytics_dir = self.data_dir / "analytics"
        self.analytics_dir.mkdir(exist_ok=True, parents=True)

        self.trades_file = self.data_dir / "trade_history.json"
        self.daily_summary_file = self.data_dir / "daily_summary.json"
        
        # NEW: Enhanced analytics files
        self.pnl_attribution_file = self.analytics_dir / "pnl_attribution.json"
        self.scans_file = self.analytics_dir / "market_scans.jsonl"
        self.capital_file = self.analytics_dir / "capital_utilization.jsonl"
        self.reason_codes_file = self.analytics_dir / "reason_codes_summary.json"

        # Load existing trade history
        self.trades: List[TradeRecord] = self._load_trades()

        # Session tracking
        self.session_start = datetime.now()
        self.session_trades: List[TradeRecord] = []
        
        # Thread safety for concurrent access
        self._lock = threading.Lock()
        
        # NEW: PnL Attribution tracking (Requirement #1)
        self.pnl_by_signal: Dict[str, float] = defaultdict(float)
        self.pnl_by_strategy: Dict[str, float] = defaultdict(float)
        self.trades_by_entry_reason: Dict[str, int] = defaultdict(int)
        self.trades_by_exit_reason: Dict[str, int] = defaultdict(int)
        
        # NEW: Market scan tracking (Requirement #3)
        self.scan_times: List[float] = []
        self.total_markets_scanned = 0
        self.total_scan_cycles = 0
        
        # Load attribution data
        self._load_pnl_attribution()

        logger.info(f"📊 Analytics initialized - {len(self.trades)} historical trades loaded")
        logger.info(f"   Analytics directory: {self.analytics_dir}")

    def calculate_entry_fee(self, size_usd: float, is_maker: bool = False) -> float:
        """
        Calculate Coinbase fee for entry order

        Args:
            size_usd: Position size in USD
            is_maker: True if maker order (limit), False if taker (market)

        Returns:
            Fee amount in USD
        """
        fee_rate = self.COINBASE_MAKER_FEE if is_maker else self.COINBASE_TAKER_FEE
        return size_usd * fee_rate

    def calculate_exit_fee(self, size_usd: float, is_maker: bool = False) -> float:
        """Calculate Coinbase fee for exit order"""
        return self.calculate_entry_fee(size_usd, is_maker)

    def record_entry(self, symbol: str, side: str, price: float, size_usd: float,
                    expected_price: float, actual_fill_price: float,
                    stop_loss: float = 0.0, take_profit: float = 0.0) -> str:
        """
        Record trade entry with fee calculation

        Returns:
            Trade ID for tracking
        """
        entry_fee = self.calculate_entry_fee(size_usd)
        slippage = actual_fill_price - expected_price
        slippage_pct = (slippage / expected_price) * 100 if expected_price > 0 else 0.0

        quantity = size_usd / actual_fill_price if actual_fill_price > 0 else 0.0

        trade = TradeRecord(
            timestamp=datetime.now().isoformat(),
            symbol=symbol,
            side=side,
            entry_price=actual_fill_price,
            size_usd=size_usd,
            quantity=quantity,
            entry_fee=entry_fee,
            expected_price=expected_price,
            actual_fill_price=actual_fill_price,
            slippage=slippage,
            slippage_pct=slippage_pct,
            stop_loss=stop_loss,
            take_profit=take_profit,
            entry_time=datetime.now().isoformat()
        )

        self.session_trades.append(trade)

        logger.info(f"💰 Entry recorded: {symbol} {side}")
        logger.info(f"   Size: ${size_usd:.2f} ({quantity:.6f} {symbol.split('-')[0]})")
        logger.info(f"   Entry fee: ${entry_fee:.4f} ({self.COINBASE_TAKER_FEE*100}%)")
        if abs(slippage_pct) > 0.01:
            logger.info(f"   Slippage: ${slippage:.4f} ({slippage_pct:+.2f}%)")

        return trade.timestamp

    def record_exit(self, symbol: str, exit_price: float, exit_reason: str = "manual") -> Optional[TradeRecord]:
        """
        Record trade exit and calculate performance

        Returns:
            Completed trade record with full P&L
        """
        # Find open trade for this symbol
        open_trade = None
        for trade in reversed(self.session_trades):
            if trade.symbol == symbol and trade.exit_price is None:
                open_trade = trade
                break

        if not open_trade:
            logger.warning(f"No open trade found for {symbol}")
            return None

        # Calculate exit fee
        exit_value = open_trade.quantity * exit_price
        exit_fee = self.calculate_exit_fee(exit_value)

        # Calculate P&L
        if open_trade.side == 'BUY':
            gross_profit = exit_value - open_trade.size_usd
        else:  # SELL/SHORT
            gross_profit = open_trade.size_usd - exit_value

        total_fees = open_trade.entry_fee + exit_fee
        net_profit = gross_profit - total_fees
        profit_pct = (net_profit / open_trade.size_usd) * 100

        # Calculate duration
        entry_dt = datetime.fromisoformat(open_trade.entry_time)
        exit_dt = datetime.now()
        duration = (exit_dt - entry_dt).total_seconds()

        # Update trade record
        open_trade.exit_price = exit_price
        open_trade.exit_fee = exit_fee
        open_trade.total_fees = total_fees
        open_trade.gross_profit = gross_profit
        open_trade.net_profit = net_profit
        open_trade.profit_pct = profit_pct
        open_trade.exit_reason = exit_reason
        open_trade.exit_time = exit_dt.isoformat()
        open_trade.duration_seconds = duration

        # Save to history
        self.trades.append(open_trade)
        self._save_trades()

        # Log results
        profit_emoji = "🟢" if net_profit > 0 else "🔴" if net_profit < 0 else "⚪"
        logger.info(f"{profit_emoji} Exit recorded: {symbol}")
        logger.info(f"   Entry: ${open_trade.entry_price:.6f} → Exit: ${exit_price:.6f}")
        logger.info(f"   Gross P&L: ${gross_profit:.4f}")
        logger.info(f"   Total fees: ${total_fees:.4f} (entry: ${open_trade.entry_fee:.4f} + exit: ${exit_fee:.4f})")
        logger.info(f"   Net P&L: ${net_profit:.4f} ({profit_pct:+.2f}%)")
        logger.info(f"   Duration: {duration:.0f}s ({duration/60:.1f}m)")
        logger.info(f"   Exit reason: {exit_reason}")

        return open_trade

    def get_session_stats(self) -> Dict:
        """Get statistics for current trading session"""
        completed = [t for t in self.session_trades if t.exit_price is not None]

        if not completed:
            return {
                'trades_count': 0,
                'wins': 0,
                'losses': 0,
                'win_rate': 0.0,
                'total_pnl': 0.0,
                'total_fees': 0.0,
                'avg_profit': 0.0,
                'avg_win': 0.0,
                'avg_loss': 0.0,
                'best_trade': 0.0,
                'worst_trade': 0.0,
                'profit_factor': 0.0,
                'avg_duration_min': 0.0
            }

        wins = [t for t in completed if t.net_profit > 0]
        losses = [t for t in completed if t.net_profit < 0]

        total_pnl = sum(t.net_profit for t in completed)
        total_fees = sum(t.total_fees for t in completed)

        return {
            'trades_count': len(completed),
            'wins': len(wins),
            'losses': len(losses),
            'win_rate': (len(wins) / len(completed) * 100) if completed else 0.0,
            'total_pnl': total_pnl,
            'total_fees': total_fees,
            'avg_profit': total_pnl / len(completed) if completed else 0.0,
            'avg_win': sum(t.net_profit for t in wins) / len(wins) if wins else 0.0,
            'avg_loss': sum(t.net_profit for t in losses) / len(losses) if losses else 0.0,
            'best_trade': max((t.net_profit for t in completed), default=0.0),
            'worst_trade': min((t.net_profit for t in completed), default=0.0),
            'profit_factor': abs(sum(t.net_profit for t in wins) / sum(t.net_profit for t in losses)) if losses else float('inf'),
            'avg_duration_min': sum(t.duration_seconds for t in completed) / len(completed) / 60 if completed else 0.0
        }

    def print_session_report(self):
        """Print formatted session performance report"""
        stats = self.get_session_stats()

        logger.info("\n" + "="*70)
        logger.info("📊 SESSION PERFORMANCE REPORT")
        logger.info("="*70)
        logger.info(f"Total Trades: {stats['trades_count']}")
        logger.info(f"Wins: {stats['wins']} | Losses: {stats['losses']} | Win Rate: {stats['win_rate']:.1f}%")
        logger.info(f"")
        logger.info(f"💰 P&L:")
        logger.info(f"   Total P&L: ${stats['total_pnl']:.2f}")
        logger.info(f"   Total Fees: ${stats['total_fees']:.2f}")
        logger.info(f"   Net After Fees: ${stats['total_pnl']:.2f}")
        logger.info(f"")
        logger.info(f"📈 Averages:")
        logger.info(f"   Avg Profit per Trade: ${stats['avg_profit']:.4f}")
        logger.info(f"   Avg Winning Trade: ${stats['avg_win']:.4f}")
        logger.info(f"   Avg Losing Trade: ${stats['avg_loss']:.4f}")
        logger.info(f"   Avg Trade Duration: {stats['avg_duration_min']:.1f}m")
        logger.info(f"")
        logger.info(f"🎯 Best/Worst:")
        logger.info(f"   Best Trade: ${stats['best_trade']:.4f}")
        logger.info(f"   Worst Trade: ${stats['worst_trade']:.4f}")
        if stats['profit_factor'] != float('inf'):
            logger.info(f"   Profit Factor: {stats['profit_factor']:.2f}")
        logger.info("="*70 + "\n")

    def export_to_csv(self, filename: Optional[str] = None) -> str:
        """
        Export trade history to CSV

        Returns:
            Path to exported CSV file
        """
        if filename is None:
            filename = f"trades_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"

        csv_path = self.data_dir / filename

        with open(csv_path, 'w') as f:
            # Header
            f.write("timestamp,symbol,side,entry_price,exit_price,size_usd,quantity,")
            f.write("entry_fee,exit_fee,total_fees,gross_profit,net_profit,profit_pct,")
            f.write("slippage,slippage_pct,duration_seconds,exit_reason\n")

            # Data rows
            for trade in self.trades:
                if trade.exit_price is not None:  # Only completed trades
                    f.write(f"{trade.timestamp},{trade.symbol},{trade.side},")
                    f.write(f"{trade.entry_price:.6f},{trade.exit_price:.6f},")
                    f.write(f"{trade.size_usd:.2f},{trade.quantity:.6f},")
                    f.write(f"{trade.entry_fee:.4f},{trade.exit_fee:.4f},{trade.total_fees:.4f},")
                    f.write(f"{trade.gross_profit:.4f},{trade.net_profit:.4f},{trade.profit_pct:.2f},")
                    f.write(f"{trade.slippage:.4f},{trade.slippage_pct:.2f},")
                    f.write(f"{trade.duration_seconds:.0f},{trade.exit_reason}\n")

        logger.info(f"📄 Trade history exported to {csv_path}")
        return str(csv_path)

    def _load_trades(self) -> List[TradeRecord]:
        """Load trade history from JSON file"""
        if not self.trades_file.exists():
            return []

        try:
            with open(self.trades_file, 'r') as f:
                data = json.load(f)
                return [TradeRecord(**t) for t in data]
        except Exception as e:
            logger.warning(f"Could not load trade history: {e}")
            return []

    def _save_trades(self):
        """Save trade history to JSON file"""
        try:
            with open(self.trades_file, 'w') as f:
                data = [asdict(t) for t in self.trades]
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save trade history: {e}")
    
    # ========================================================================
    # REQUIREMENT #1: PnL Attribution Logging
    # ========================================================================
    
    def _load_pnl_attribution(self):
        """Load existing PnL attribution data"""
        if not self.pnl_attribution_file.exists():
            return
        
        try:
            with open(self.pnl_attribution_file, 'r') as f:
                data = json.load(f)
            
            self.pnl_by_signal = defaultdict(float, data.get('by_signal', {}))
            self.pnl_by_strategy = defaultdict(float, data.get('by_strategy', {}))
            self.trades_by_entry_reason = defaultdict(int, data.get('entry_reasons', {}))
            self.trades_by_exit_reason = defaultdict(int, data.get('exit_reasons', {}))
            
            logger.info("📊 Loaded PnL attribution data")
        except Exception as e:
            logger.error(f"Failed to load PnL attribution: {e}")
    
    def _save_pnl_attribution(self):
        """Save PnL attribution data"""
        with self._lock:
            try:
                data = {
                    'by_signal': dict(self.pnl_by_signal),
                    'by_strategy': dict(self.pnl_by_strategy),
                    'entry_reasons': dict(self.trades_by_entry_reason),
                    'exit_reasons': dict(self.trades_by_exit_reason),
                    'last_updated': datetime.now().isoformat()
                }
                
                # Atomic write
                temp_file = self.pnl_attribution_file.with_suffix('.tmp')
                with open(temp_file, 'w') as f:
                    json.dump(data, f, indent=2)
                temp_file.replace(self.pnl_attribution_file)
                
            except Exception as e:
                logger.error(f"Failed to save PnL attribution: {e}")
    
    def update_pnl_attribution(self, trade: TradeRecord):
        """Update PnL attribution when a trade completes"""
        if trade.exit_price is None:
            return  # Trade not completed
        
        with self._lock:
            # Update signal-based attribution
            self.pnl_by_signal[trade.entry_signal_type] += trade.net_profit
            
            # Update strategy-based attribution
            self.pnl_by_strategy[trade.strategy_name] += trade.net_profit
            
            # Update reason codes
            self.trades_by_entry_reason[trade.entry_reason] += 1
            self.trades_by_exit_reason[trade.exit_reason] += 1
            
            # Save updated attribution
            self._save_pnl_attribution()
        
        logger.info(f"📊 Updated PnL attribution for {trade.symbol}")
        logger.info(f"   Signal: {trade.entry_signal_type} → ${trade.net_profit:.2f}")
        logger.info(f"   Strategy: {trade.strategy_name}")
    
    def get_pnl_attribution(self) -> Dict[str, Any]:
        """
        Get PnL attribution summary.
        
        Returns:
            Dict with PnL broken down by signal type and strategy
        """
        with self._lock:
            return {
                'by_signal': dict(self.pnl_by_signal),
                'by_strategy': dict(self.pnl_by_strategy),
                'entry_reasons': dict(self.trades_by_entry_reason),
                'exit_reasons': dict(self.trades_by_exit_reason),
                'timestamp': datetime.now().isoformat()
            }
    
    # ========================================================================
    # REQUIREMENT #2: Trade Outcome Reason Codes
    # ========================================================================
    
    def get_reason_code_summary(self) -> Dict[str, Any]:
        """
        Get summary of trade reason codes.
        
        Returns:
            Dict with entry/exit reason statistics
        """
        with self._lock:
            total_trades = sum(self.trades_by_entry_reason.values())
            
            # Calculate percentages
            entry_pct = {}
            for reason, count in self.trades_by_entry_reason.items():
                entry_pct[reason] = {
                    'count': count,
                    'percentage': (count / total_trades * 100) if total_trades > 0 else 0.0
                }
            
            exit_pct = {}
            for reason, count in self.trades_by_exit_reason.items():
                exit_pct[reason] = {
                    'count': count,
                    'percentage': (count / total_trades * 100) if total_trades > 0 else 0.0
                }
            
            return {
                'entry_reasons': entry_pct,
                'exit_reasons': exit_pct,
                'total_trades': total_trades,
                'timestamp': datetime.now().isoformat()
            }
    
    # ========================================================================
    # REQUIREMENT #3: Market Scan Timing Metrics
    # ========================================================================
    
    def log_market_scan(self, metrics: MarketScanMetrics):
        """
        Log market scan timing metrics.
        
        Tracks whether 732 markets are scanned in acceptable time.
        """
        with self._lock:
            # Update aggregates
            self.scan_times.append(metrics.duration_seconds)
            self.total_markets_scanned += metrics.markets_scanned
            self.total_scan_cycles += 1
            
            # Keep only last 100 scans in memory
            if len(self.scan_times) > 100:
                self.scan_times.pop(0)
            
            # Write to JSONL file (append-only)
            try:
                with open(self.scans_file, 'a') as f:
                    f.write(json.dumps(asdict(metrics)) + '\n')
            except Exception as e:
                logger.error(f"Failed to write scan metrics: {e}")
        
        # Log scan performance
        logger.info("=" * 70)
        logger.info("🔍 MARKET SCAN METRICS")
        logger.info("=" * 70)
        logger.info(f"   Markets Scanned: {metrics.markets_scanned}/{metrics.total_markets_available}")
        logger.info(f"   Scan Duration: {metrics.duration_seconds:.2f}s")
        logger.info(f"   Avg Time/Market: {metrics.avg_time_per_market_ms:.0f}ms")
        logger.info(f"   Rate Limit Delays: {metrics.total_rate_limit_delays_ms:.0f}ms")
        logger.info(f"   Signals Generated: {metrics.signals_generated}")
        logger.info(f"   Trades Executed: {metrics.trades_executed}")
        logger.info("=" * 70)
    
    def get_scan_performance(self) -> Dict[str, Any]:
        """
        Get market scan performance summary.
        
        Returns:
            Dict with scan timing statistics
        """
        with self._lock:
            if not self.scan_times:
                return {
                    'avg_scan_time_seconds': 0.0,
                    'min_scan_time_seconds': 0.0,
                    'max_scan_time_seconds': 0.0,
                    'total_markets_scanned': 0,
                    'total_scan_cycles': 0,
                    'avg_markets_per_scan': 0.0,
                    'estimated_full_scan_time': 0.0
                }
            
            avg_markets_per_scan = (
                self.total_markets_scanned / self.total_scan_cycles
                if self.total_scan_cycles > 0 else 0.0
            )
            
            avg_scan_time = sum(self.scan_times) / len(self.scan_times)
            
            # Estimate time to scan all 732 markets
            if avg_markets_per_scan > 0:
                estimated_full_scan_time = (732 / avg_markets_per_scan) * avg_scan_time
            else:
                estimated_full_scan_time = 0.0
            
            return {
                'avg_scan_time_seconds': avg_scan_time,
                'min_scan_time_seconds': min(self.scan_times),
                'max_scan_time_seconds': max(self.scan_times),
                'total_markets_scanned': self.total_markets_scanned,
                'total_scan_cycles': self.total_scan_cycles,
                'avg_markets_per_scan': avg_markets_per_scan,
                'estimated_full_scan_time': estimated_full_scan_time,
                'timestamp': datetime.now().isoformat()
            }
    
    # ========================================================================
    # REQUIREMENT #4: Capital Utilization Reports
    # ========================================================================
    
    def log_capital_utilization(self, utilization: CapitalUtilization):
        """
        Log capital utilization snapshot.
        
        Tracks idle vs active capital deployment.
        """
        with self._lock:
            # Write to JSONL file (append-only)
            try:
                with open(self.capital_file, 'a') as f:
                    f.write(json.dumps(asdict(utilization)) + '\n')
            except Exception as e:
                logger.error(f"Failed to write capital utilization: {e}")
        
        logger.info("=" * 70)
        logger.info("💰 CAPITAL UTILIZATION")
        logger.info("=" * 70)
        logger.info(f"   Total Capital: ${utilization.total_capital_usd:.2f}")
        logger.info(f"   In Positions: ${utilization.capital_in_positions_usd:.2f}")
        logger.info(f"   Idle Capital: ${utilization.idle_capital_usd:.2f}")
        logger.info(f"   Utilization: {utilization.utilization_pct:.1f}%")
        logger.info(f"   Positions: {utilization.num_positions}")
        logger.info(f"   Avg Position: ${utilization.avg_position_size_usd:.2f}")
        logger.info(f"   Unrealized P&L: ${utilization.unrealized_pnl_usd:.2f}")
        logger.info("=" * 70)
    
    def get_recent_capital_utilization(self, hours: int = 24) -> List[Dict[str, Any]]:
        """
        Get recent capital utilization data.
        
        Args:
            hours: Number of hours to look back
        
        Returns:
            List of capital utilization snapshots
        """
        cutoff_time = datetime.now() - timedelta(hours=hours)
        recent_data = []
        
        if not self.capital_file.exists():
            return recent_data
        
        try:
            with open(self.capital_file, 'r') as f:
                for line in f:
                    entry = json.loads(line)
                    timestamp = datetime.fromisoformat(entry['timestamp'])
                    if timestamp >= cutoff_time:
                        recent_data.append(entry)
        except Exception as e:
            logger.error(f"Failed to read capital utilization data: {e}")
        
        return recent_data
    
    # ========================================================================
    # COMPREHENSIVE REPORTING
    # ========================================================================
    
    def generate_analytics_report(self) -> str:
        """
        Generate comprehensive analytics report.
        
        Returns:
            Formatted report string
        """
        pnl_attribution = self.get_pnl_attribution()
        reason_codes = self.get_reason_code_summary()
        scan_performance = self.get_scan_performance()
        
        report = []
        report.append("=" * 70)
        report.append("NIJA TRADE ANALYTICS REPORT")
        report.append("=" * 70)
        report.append(f"Generated: {datetime.now().isoformat()}")
        report.append("")
        
        # PnL Attribution
        report.append("1. PnL ATTRIBUTION BY SIGNAL TYPE")
        report.append("-" * 70)
        total_signal_pnl = sum(pnl_attribution['by_signal'].values())
        for signal, pnl in sorted(pnl_attribution['by_signal'].items(), key=lambda x: x[1], reverse=True):
            pct = (pnl / total_signal_pnl * 100) if total_signal_pnl != 0 else 0
            report.append(f"   {signal}: ${pnl:.2f} ({pct:.1f}%)")
        report.append(f"   TOTAL: ${total_signal_pnl:.2f}")
        report.append("")
        
        report.append("   PnL ATTRIBUTION BY STRATEGY")
        report.append("-" * 70)
        for strategy, pnl in sorted(pnl_attribution['by_strategy'].items(), key=lambda x: x[1], reverse=True):
            report.append(f"   {strategy}: ${pnl:.2f}")
        report.append("")
        
        # Reason Codes
        report.append("2. TRADE OUTCOME REASON CODES")
        report.append("-" * 70)
        report.append("   Entry Reasons (Top 5):")
        entry_sorted = sorted(
            reason_codes['entry_reasons'].items(),
            key=lambda x: x[1]['count'],
            reverse=True
        )[:5]
        for reason, data in entry_sorted:
            report.append(f"      {reason}: {data['count']} trades ({data['percentage']:.1f}%)")
        report.append("")
        report.append("   Exit Reasons (Top 5):")
        exit_sorted = sorted(
            reason_codes['exit_reasons'].items(),
            key=lambda x: x[1]['count'],
            reverse=True
        )[:5]
        for reason, data in exit_sorted:
            report.append(f"      {reason}: {data['count']} trades ({data['percentage']:.1f}%)")
        report.append("")
        
        # Scan Performance
        report.append("3. MARKET SCAN PERFORMANCE")
        report.append("-" * 70)
        report.append(f"   Total Scan Cycles: {scan_performance['total_scan_cycles']}")
        report.append(f"   Total Markets Scanned: {scan_performance['total_markets_scanned']}")
        report.append(f"   Avg Markets/Scan: {scan_performance['avg_markets_per_scan']:.1f}")
        report.append(f"   Avg Scan Time: {scan_performance['avg_scan_time_seconds']:.2f}s")
        report.append(f"   Min Scan Time: {scan_performance['min_scan_time_seconds']:.2f}s")
        report.append(f"   Max Scan Time: {scan_performance['max_scan_time_seconds']:.2f}s")
        if scan_performance['estimated_full_scan_time'] > 0:
            report.append(f"   Est. Time for 732 Markets: {scan_performance['estimated_full_scan_time']:.0f}s ({scan_performance['estimated_full_scan_time']/60:.1f}m)")
        report.append("")
        
        # Capital Utilization (latest snapshot)
        recent_capital = self.get_recent_capital_utilization(hours=1)
        if recent_capital:
            latest = recent_capital[-1]
            report.append("4. CAPITAL UTILIZATION (Latest)")
            report.append("-" * 70)
            report.append(f"   Total Capital: ${latest['total_capital_usd']:.2f}")
            report.append(f"   In Positions: ${latest['capital_in_positions_usd']:.2f} ({latest['utilization_pct']:.1f}%)")
            report.append(f"   Idle Capital: ${latest['idle_capital_usd']:.2f}")
            report.append(f"   Number of Positions: {latest['num_positions']}")
            if latest['num_positions'] > 0:
                report.append(f"   Avg Position Size: ${latest['avg_position_size_usd']:.2f}")
                report.append(f"   Largest Position: {latest['largest_position_symbol']} (${latest['largest_position_usd']:.2f})")
            report.append(f"   Unrealized P&L: ${latest['unrealized_pnl_usd']:.2f}")
        
        report.append("=" * 70)
        
        return "\n".join(report)
    
    def print_analytics_report(self):
        """Print the comprehensive analytics report"""
        report = self.generate_analytics_report()
        logger.info("\n" + report)


# ============================================================================
# SINGLETON INSTANCE
# ============================================================================

_analytics_instance: Optional[TradeAnalytics] = None
_analytics_lock = threading.Lock()


def get_analytics(data_dir: str = "./data") -> TradeAnalytics:
    """
    Get singleton analytics instance.
    
    Args:
        data_dir: Data directory (only used on first call)
    
    Returns:
        TradeAnalytics instance
    """
    global _analytics_instance
    
    if _analytics_instance is None:
        with _analytics_lock:
            if _analytics_instance is None:
                _analytics_instance = TradeAnalytics(data_dir)
    
    return _analytics_instance
