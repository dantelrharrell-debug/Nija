"""
NIJA Trade Ledger Database Module
==================================

SQLite database for persistent trade tracking with:
- Trade ledger (all BUY/SELL transactions)
- Open positions tracking
- Trade history with full P&L
- Export capabilities (CSV/PDF)

Author: NIJA Trading Systems
Date: January 21, 2026
"""

import sqlite3
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from contextlib import contextmanager
import csv
import io

logger = logging.getLogger("nija.trade_ledger")


class TradeLedgerDB:
    """
    SQLite database manager for trade ledger
    Handles all trade recording and querying operations
    """

    def __init__(self, db_path: str = "./data/trade_ledger.db"):
        """
        Initialize trade ledger database

        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(exist_ok=True, parents=True)

        # Initialize database schema
        self._init_database()

        logger.info(f"📊 Trade Ledger DB initialized at {self.db_path}")

    @contextmanager
    def _get_connection(self):
        """Context manager for database connections"""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row  # Return rows as dictionaries
        try:
            yield conn
            conn.commit()
        except Exception as e:
            conn.rollback()
            logger.error(f"Database error: {e}")
            raise
        finally:
            conn.close()

    def _init_database(self):
        """Create database schema if it doesn't exist"""
        with self._get_connection() as conn:
            cursor = conn.cursor()

            # Trade ledger table - records every BUY/SELL
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS trade_ledger (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    user_id TEXT DEFAULT 'platform',
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    action TEXT NOT NULL,
                    price REAL NOT NULL,
                    quantity REAL NOT NULL,
                    size_usd REAL NOT NULL,
                    fee REAL DEFAULT 0.0,
                    order_id TEXT,
                    position_id TEXT,
                    platform_trade_id TEXT,
                    notes TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # CRITICAL FIX (Jan 22, 2026): Ensure platform_trade_id column exists in existing databases
            # This migration is idempotent and safe to run multiple times
            self._migrate_add_platform_trade_id(cursor)

            # Open positions table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS open_positions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    position_id TEXT UNIQUE NOT NULL,
                    user_id TEXT DEFAULT 'platform',
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    entry_price REAL NOT NULL,
                    quantity REAL NOT NULL,
                    size_usd REAL NOT NULL,
                    stop_loss REAL,
                    take_profit_1 REAL,
                    take_profit_2 REAL,
                    take_profit_3 REAL,
                    entry_fee REAL DEFAULT 0.0,
                    entry_time TEXT NOT NULL,
                    status TEXT DEFAULT 'open',
                    notes TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Completed trades table (closed positions with P&L)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS completed_trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    position_id TEXT UNIQUE NOT NULL,
                    user_id TEXT DEFAULT 'platform',
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    entry_price REAL NOT NULL,
                    exit_price REAL NOT NULL,
                    quantity REAL NOT NULL,
                    size_usd REAL NOT NULL,
                    entry_fee REAL DEFAULT 0.0,
                    exit_fee REAL DEFAULT 0.0,
                    total_fees REAL DEFAULT 0.0,
                    gross_profit REAL DEFAULT 0.0,
                    net_profit REAL DEFAULT 0.0,
                    profit_pct REAL DEFAULT 0.0,
                    entry_time TEXT NOT NULL,
                    exit_time TEXT NOT NULL,
                    duration_seconds REAL DEFAULT 0.0,
                    exit_reason TEXT,
                    notes TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # P2: Copy trade map table - tracks master trade → user executions
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS copy_trade_map (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    platform_trade_id TEXT NOT NULL,
                    platform_user_id TEXT DEFAULT 'platform',
                    master_symbol TEXT NOT NULL,
                    master_side TEXT NOT NULL,
                    master_order_id TEXT,
                    master_timestamp TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    user_status TEXT NOT NULL,
                    user_order_id TEXT,
                    user_error TEXT,
                    user_size REAL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Create indexes for performance
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_ledger_symbol
                ON trade_ledger(symbol)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_ledger_timestamp
                ON trade_ledger(timestamp)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_ledger_user
                ON trade_ledger(user_id)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_ledger_master_trade
                ON trade_ledger(platform_trade_id)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_positions_symbol
                ON open_positions(symbol)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_positions_user
                ON open_positions(user_id)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_completed_symbol
                ON completed_trades(symbol)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_completed_user
                ON completed_trades(user_id)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_completed_time
                ON completed_trades(exit_time)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_copy_trade_map_master
                ON copy_trade_map(platform_trade_id)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_copy_trade_map_user
                ON copy_trade_map(user_id)
            """)

            # POSITION SOURCE TRACKING (Feb 8, 2026): Add position_source field to distinguish
            # NIJA-managed positions from existing holdings
            # Run this AFTER all tables are created
            self._migrate_add_position_source(cursor)

            logger.info("✅ Database schema initialized")

    def _migrate_add_platform_trade_id(self, cursor):
        """
        Migration: Add platform_trade_id column to trade_ledger table if it doesn't exist.

        CRITICAL FIX (Jan 22, 2026): Ensure existing databases have platform_trade_id column.
        This is required for copy trading visibility and trade attribution.

        Args:
            cursor: SQLite cursor
        """
        try:
            # Check if column exists by querying table info
            cursor.execute("PRAGMA table_info(trade_ledger)")
            columns = [row[1] for row in cursor.fetchall()]

            if 'platform_trade_id' not in columns:
                logger.info("🔧 Running migration: Adding platform_trade_id column to trade_ledger")
                cursor.execute("""
                    ALTER TABLE trade_ledger
                    ADD COLUMN platform_trade_id TEXT
                """)

                # Add index for performance
                cursor.execute("""
                    CREATE INDEX IF NOT EXISTS idx_ledger_master_trade
                    ON trade_ledger(platform_trade_id)
                """)

                logger.info("✅ Migration complete: platform_trade_id column added")
            else:
                logger.debug("✓ platform_trade_id column already exists")
        except sqlite3.OperationalError as e:
            # Expected error: column already exists from a previous migration
            # This can happen if ALTER TABLE was run but column check failed
            if 'duplicate column name' in str(e).lower():
                logger.debug(f"Column already exists (duplicate column error): {e}")
            else:
                # Unexpected operational error - re-raise
                logger.error(f"Unexpected operational error during migration: {e}")
                raise
        except Exception as e:
            # Unexpected error - re-raise for visibility
            logger.error(f"Unexpected error during migration: {e}")
            raise

    def _migrate_add_position_source(self, cursor):
        """
        Migration: Add position_source column to open_positions table if it doesn't exist.

        POSITION SOURCE TRACKING (Feb 8, 2026): Track whether positions are:
        - 'nija_strategy': Opened by NIJA's trading algorithm
        - 'broker_existing': Pre-existing position (adopted on restart)
        - 'manual': Manually entered by user
        - 'unknown': Source not yet determined

        Args:
            cursor: SQLite cursor
        """
        try:
            # Check if column exists by querying table info
            cursor.execute("PRAGMA table_info(open_positions)")
            columns = [row[1] for row in cursor.fetchall()]

            if 'position_source' not in columns:
                logger.info("🔧 Running migration: Adding position_source column to open_positions")
                cursor.execute("""
                    ALTER TABLE open_positions
                    ADD COLUMN position_source TEXT DEFAULT 'unknown'
                """)

                # Add index for filtering by source
                cursor.execute("""
                    CREATE INDEX IF NOT EXISTS idx_positions_source
                    ON open_positions(position_source)
                """)

                logger.info("✅ Migration complete: position_source column added")
            else:
                logger.debug("✓ position_source column already exists")
        except sqlite3.OperationalError as e:
            # Expected error: column already exists from a previous migration
            if 'duplicate column name' in str(e).lower():
                logger.debug(f"Column already exists (duplicate column error): {e}")
            else:
                # Unexpected operational error - re-raise
                logger.error(f"Unexpected operational error during position_source migration: {e}")
                raise
        except Exception as e:
            # Unexpected error - re-raise for visibility
            logger.error(f"Unexpected error during position_source migration: {e}")
            raise

    def record_buy(self, symbol: str, price: float, quantity: float,
                   size_usd: float, fee: float = 0.0,
                   order_id: str = None, position_id: str = None,
                   user_id: str = 'platform', notes: str = None,
                   platform_trade_id: str = None) -> int:
        """
        Record a BUY transaction in the ledger

        Args:
            symbol: Trading symbol (e.g., 'BTC-USD')
            price: Execution price
            quantity: Amount of crypto purchased
            size_usd: Position size in USD
            fee: Transaction fee (default: 0.0)
            order_id: Broker order ID (optional)
            position_id: Position identifier (optional)
            user_id: User account ID (default: 'platform')
            notes: Additional notes (optional)
            platform_trade_id: Reference to master trade for copy trading visibility (optional)

        Returns:
            int: Transaction ID
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO trade_ledger
                (timestamp, user_id, symbol, side, action, price, quantity,
                 size_usd, fee, order_id, position_id, platform_trade_id, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                datetime.now().isoformat(),
                user_id,
                symbol,
                'BUY',
                'OPEN',
                price,
                quantity,
                size_usd,
                fee,
                order_id,
                position_id,
                platform_trade_id,
                notes
            ))

            tx_id = cursor.lastrowid
            logger.info(f"📝 BUY recorded: {symbol} @ ${price:.2f} (ID: {tx_id})")
            return tx_id

    def record_sell(self, symbol: str, price: float, quantity: float,
                    size_usd: float, fee: float = 0.0,
                    order_id: str = None, position_id: str = None,
                    user_id: str = 'platform', notes: str = None,
                    platform_trade_id: str = None) -> int:
        """
        Record a SELL transaction in the ledger

        Args:
            symbol: Trading symbol (e.g., 'BTC-USD')
            price: Execution price
            quantity: Amount of crypto sold
            size_usd: Position size in USD
            fee: Transaction fee (default: 0.0)
            order_id: Broker order ID (optional)
            position_id: Position identifier (optional)
            user_id: User account ID (default: 'platform')
            notes: Additional notes (optional)
            platform_trade_id: Reference to master trade for copy trading visibility (optional)

        Returns:
            int: Transaction ID
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO trade_ledger
                (timestamp, user_id, symbol, side, action, price, quantity,
                 size_usd, fee, order_id, position_id, platform_trade_id, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                datetime.now().isoformat(),
                user_id,
                symbol,
                'SELL',
                'CLOSE',
                price,
                quantity,
                size_usd,
                fee,
                order_id,
                position_id,
                platform_trade_id,
                notes
            ))

            tx_id = cursor.lastrowid
            logger.info(f"📝 SELL recorded: {symbol} @ ${price:.2f} (ID: {tx_id})")
            return tx_id

    def open_position(self, position_id: str, symbol: str, side: str,
                     entry_price: float, quantity: float, size_usd: float,
                     stop_loss: float = None, take_profit_1: float = None,
                     take_profit_2: float = None, take_profit_3: float = None,
                     entry_fee: float = 0.0, user_id: str = 'platform',
                     notes: str = None, position_source: str = 'nija_strategy') -> bool:
        """
        Record a new open position

        Args:
            position_id: Unique position identifier
            symbol: Trading symbol
            side: Position side (long/short)
            entry_price: Entry price
            quantity: Position quantity
            size_usd: Position size in USD
            stop_loss: Stop loss price (optional)
            take_profit_1/2/3: Take profit targets (optional)
            entry_fee: Entry transaction fee
            user_id: User account ID
            notes: Additional notes
            position_source: Source of position ('nija_strategy', 'broker_existing', 'manual', 'unknown')

        Returns:
            True if successful
        """
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO open_positions
                    (position_id, user_id, symbol, side, entry_price, quantity,
                     size_usd, stop_loss, take_profit_1, take_profit_2,
                     take_profit_3, entry_fee, entry_time, notes, position_source)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    position_id,
                    user_id,
                    symbol,
                    side,
                    entry_price,
                    quantity,
                    size_usd,
                    stop_loss,
                    take_profit_1,
                    take_profit_2,
                    take_profit_3,
                    entry_fee,
                    datetime.now().isoformat(),
                    notes,
                    position_source
                ))

                logger.info(f"📈 Position opened: {symbol} {side} (ID: {position_id}, Source: {position_source})")
                return True
        except sqlite3.IntegrityError:
            logger.warning(f"Position {position_id} already exists")
            return False
        except Exception as e:
            logger.error(f"Error opening position: {e}")
            return False

    def close_position(self, position_id: str, exit_price: float,
                      exit_fee: float = 0.0, exit_reason: str = None) -> bool:
        """
        Close a position and move it to completed trades

        Returns:
            True if successful
        """
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()

                # Get open position
                cursor.execute("""
                    SELECT * FROM open_positions WHERE position_id = ?
                """, (position_id,))

                position = cursor.fetchone()
                if not position:
                    logger.warning(f"Position {position_id} not found")
                    return False

                # Calculate P&L
                entry_price = position['entry_price']
                quantity = position['quantity']
                size_usd = position['size_usd']
                entry_fee = position['entry_fee']
                side = position['side']

                exit_value = quantity * exit_price

                # Correct P&L calculation for LONG and SHORT positions
                if side.upper() in ('LONG', 'BUY'):
                    # For LONG: profit when price goes up
                    gross_profit = exit_value - size_usd
                else:  # SHORT or SELL
                    # For SHORT: profit when price goes down
                    # Entry: Sell high (receive size_usd)
                    # Exit: Buy low (pay exit_value)
                    gross_profit = size_usd - exit_value

                total_fees = entry_fee + exit_fee
                net_profit = gross_profit - total_fees
                profit_pct = (net_profit / size_usd) * 100

                # Calculate duration
                entry_time = datetime.fromisoformat(position['entry_time'])
                exit_time = datetime.now()
                duration = (exit_time - entry_time).total_seconds()

                # Insert into completed trades
                cursor.execute("""
                    INSERT INTO completed_trades
                    (position_id, user_id, symbol, side, entry_price, exit_price,
                     quantity, size_usd, entry_fee, exit_fee, total_fees,
                     gross_profit, net_profit, profit_pct, entry_time, exit_time,
                     duration_seconds, exit_reason, notes)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    position_id,
                    position['user_id'],
                    position['symbol'],
                    side,
                    entry_price,
                    exit_price,
                    quantity,
                    size_usd,
                    entry_fee,
                    exit_fee,
                    total_fees,
                    gross_profit,
                    net_profit,
                    profit_pct,
                    position['entry_time'],
                    exit_time.isoformat(),
                    duration,
                    exit_reason,
                    position['notes']
                ))

                # Delete from open positions
                cursor.execute("""
                    DELETE FROM open_positions WHERE position_id = ?
                """, (position_id,))

                profit_emoji = "🟢" if net_profit > 0 else "🔴" if net_profit < 0 else "⚪"
                logger.info(f"{profit_emoji} Position closed: {position['symbol']} "
                           f"P&L: ${net_profit:.2f} ({profit_pct:+.2f}%)")

                return True

        except Exception as e:
            logger.error(f"Error closing position: {e}")
            return False

    def get_open_positions(self, user_id: str = None, symbol: str = None) -> List[Dict]:
        """
        Get all open positions

        Args:
            user_id: Filter by user ID (optional)
            symbol: Filter by symbol (optional)

        Returns:
            List of open position dictionaries
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()

            query = "SELECT * FROM open_positions WHERE 1=1"
            params = []

            if user_id:
                query += " AND user_id = ?"
                params.append(user_id)

            if symbol:
                query += " AND symbol = ?"
                params.append(symbol)

            query += " ORDER BY entry_time DESC"

            cursor.execute(query, params)

            positions = []
            for row in cursor.fetchall():
                positions.append(dict(row))

            return positions

    def get_trade_history(self, user_id: str = None, symbol: str = None,
                         limit: int = 100, offset: int = 0) -> List[Dict]:
        """
        Get completed trade history

        Args:
            user_id: Filter by user ID (optional)
            symbol: Filter by symbol (optional)
            limit: Maximum number of results
            offset: Result offset for pagination

        Returns:
            List of completed trade dictionaries
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()

            query = "SELECT * FROM completed_trades WHERE 1=1"
            params = []

            if user_id:
                query += " AND user_id = ?"
                params.append(user_id)

            if symbol:
                query += " AND symbol = ?"
                params.append(symbol)

            query += " ORDER BY exit_time DESC LIMIT ? OFFSET ?"
            params.extend([limit, offset])

            cursor.execute(query, params)

            trades = []
            for row in cursor.fetchall():
                trades.append(dict(row))

            return trades

    def get_ledger_transactions(self, user_id: str = None, symbol: str = None,
                               limit: int = 100) -> List[Dict]:
        """
        Get raw ledger transactions (all BUY/SELL records)

        Returns:
            List of transaction dictionaries
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()

            query = "SELECT * FROM trade_ledger WHERE 1=1"
            params = []

            if user_id:
                query += " AND user_id = ?"
                params.append(user_id)

            if symbol:
                query += " AND symbol = ?"
                params.append(symbol)

            query += " ORDER BY timestamp DESC LIMIT ?"
            params.append(limit)

            cursor.execute(query, params)

            transactions = []
            for row in cursor.fetchall():
                transactions.append(dict(row))

            return transactions

    def export_to_csv(self, table: str = 'completed_trades',
                     user_id: str = None) -> str:
        """
        Export table data to CSV format

        Args:
            table: Table name ('trade_ledger', 'open_positions', 'completed_trades')
            user_id: Filter by user ID (optional)

        Returns:
            CSV string
        """
        # Validate table name against whitelist to prevent SQL injection
        valid_tables = {
            'trade_ledger': 'trade_ledger',
            'open_positions': 'open_positions',
            'completed_trades': 'completed_trades'
        }

        if table not in valid_tables:
            raise ValueError(f"Invalid table name. Must be one of: {', '.join(valid_tables.keys())}")

        # Use validated table name
        safe_table = valid_tables[table]

        with self._get_connection() as conn:
            cursor = conn.cursor()

            # Build query with parameterized user filter
            query = f"SELECT * FROM {safe_table} WHERE 1=1"
            params = []

            if user_id:
                query += " AND user_id = ?"
                params.append(user_id)

            query += " ORDER BY created_at DESC"

            cursor.execute(query, params)

            # Get column names
            columns = [description[0] for description in cursor.description]

            # Write CSV
            output = io.StringIO()
            writer = csv.DictWriter(output, fieldnames=columns)
            writer.writeheader()

            for row in cursor.fetchall():
                writer.writerow(dict(row))

            return output.getvalue()

    def get_statistics(self, user_id: str = None) -> Dict:
        """
        Get trading statistics

        Returns:
            Dictionary with stats
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()

            # Build user filter
            user_filter = ""
            params = []
            if user_id:
                user_filter = "WHERE user_id = ?"
                params.append(user_id)

            # Get completed trades stats
            cursor.execute(f"""
                SELECT
                    COUNT(*) as total_trades,
                    SUM(net_profit) as total_pnl,
                    AVG(net_profit) as avg_pnl,
                    SUM(CASE WHEN net_profit > 0 THEN 1 ELSE 0 END) as winners,
                    SUM(CASE WHEN net_profit < 0 THEN 1 ELSE 0 END) as losers,
                    MAX(net_profit) as best_trade,
                    MIN(net_profit) as worst_trade,
                    SUM(total_fees) as total_fees
                FROM completed_trades
                {user_filter}
            """, params)

            stats = dict(cursor.fetchone())

            # Get open positions count
            cursor.execute(f"""
                SELECT COUNT(*) as open_positions
                FROM open_positions
                {user_filter}
            """, params)

            stats['open_positions'] = cursor.fetchone()['open_positions']

            # Calculate win rate
            if stats['total_trades'] and stats['total_trades'] > 0:
                stats['win_rate'] = (stats['winners'] / stats['total_trades']) * 100
            else:
                stats['win_rate'] = 0.0

            return stats

    def record_copy_trade(self, platform_trade_id: str, master_symbol: str,
                         master_side: str, master_order_id: str = None,
                         platform_user_id: str = 'platform',
                         user_id: str = None, user_status: str = None,
                         user_order_id: str = None, user_error: str = None,
                         user_size: float = None) -> int:
        """
        P2: Record a copy trade execution for visibility

        Args:
            platform_trade_id: Master trade identifier
            master_symbol: Trading symbol
            master_side: 'buy' or 'sell'
            master_order_id: Master order ID
            platform_user_id: Master user ID (default: 'platform')
            user_id: User account ID
            user_status: Execution status ('filled', 'skipped', 'failed')
            user_order_id: User's order ID (if filled)
            user_error: Error message (if failed)
            user_size: User's position size

        Returns:
            Record ID
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO copy_trade_map
                (platform_trade_id, platform_user_id, master_symbol, master_side,
                 master_order_id, master_timestamp, user_id, user_status,
                 user_order_id, user_error, user_size)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                platform_trade_id,
                platform_user_id,
                master_symbol,
                master_side,
                master_order_id,
                datetime.now().isoformat(),
                user_id,
                user_status,
                user_order_id,
                user_error,
                user_size
            ))

            record_id = cursor.lastrowid
            logger.info(f"📊 Copy trade recorded: {platform_trade_id} → {user_id} ({user_status})")
            return record_id

    def get_copy_trade_map(self, platform_trade_id: str = None) -> List[Dict]:
        """
        P2: Get copy trade map showing master trade → user executions

        Args:
            platform_trade_id: Filter by specific master trade (optional)

        Returns:
            List of copy trade execution records
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()

            if platform_trade_id:
                query = """
                    SELECT * FROM copy_trade_map
                    WHERE platform_trade_id = ?
                    ORDER BY created_at DESC
                """
                cursor.execute(query, (platform_trade_id,))
            else:
                query = """
                    SELECT * FROM copy_trade_map
                    ORDER BY created_at DESC
                    LIMIT 100
                """
                cursor.execute(query)

            results = []
            for row in cursor.fetchall():
                results.append(dict(row))

            return results

    def get_copy_trade_summary(self, platform_trade_id: str) -> Dict:
        """
        P2: Get summary of copy trade execution for a master trade

        Args:
            platform_trade_id: Master trade identifier

        Returns:
            Dictionary with execution summary
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()

            cursor.execute("""
                SELECT
                    COUNT(*) as total_users,
                    SUM(CASE WHEN user_status = 'filled' THEN 1 ELSE 0 END) as filled_count,
                    SUM(CASE WHEN user_status = 'skipped' THEN 1 ELSE 0 END) as skipped_count,
                    SUM(CASE WHEN user_status = 'failed' THEN 1 ELSE 0 END) as failed_count,
                    master_symbol,
                    master_side
                FROM copy_trade_map
                WHERE platform_trade_id = ?
                GROUP BY platform_trade_id
            """, (platform_trade_id,))

            row = cursor.fetchone()
            if row:
                return dict(row)
            else:
                return {
                    'total_users': 0,
                    'filled_count': 0,
                    'skipped_count': 0,
                    'failed_count': 0,
                    'master_symbol': None,
                    'master_side': None
                }


# Global instance
_trade_ledger_db = None


def get_trade_ledger_db(db_path: str = "./data/trade_ledger.db") -> TradeLedgerDB:
    """
    Get singleton instance of trade ledger database

    Returns:
        TradeLedgerDB instance
    """
    global _trade_ledger_db

    if _trade_ledger_db is None:
        _trade_ledger_db = TradeLedgerDB(db_path)

    return _trade_ledger_db


if __name__ == "__main__":
    # Test the database
    logging.basicConfig(level=logging.INFO)

    db = get_trade_ledger_db()

    # Test recording a trade
    print("\n=== Testing Trade Recording ===")
    tx_id = db.record_buy(
        symbol="BTC-USD",
        price=50000.0,
        quantity=0.002,
        size_usd=100.0,
        fee=0.6,
        position_id="test_pos_1"
    )
    print(f"Buy transaction ID: {tx_id}")

    # Open position
    db.open_position(
        position_id="test_pos_1",
        symbol="BTC-USD",
        side="LONG",
        entry_price=50000.0,
        quantity=0.002,
        size_usd=100.0,
        stop_loss=49000.0,
        take_profit_1=51000.0,
        entry_fee=0.6
    )

    # Get open positions
    print("\n=== Open Positions ===")
    positions = db.get_open_positions()
    for pos in positions:
        print(f"{pos['symbol']} {pos['side']} @ ${pos['entry_price']:.2f}")

    # Close position
    db.record_sell(
        symbol="BTC-USD",
        price=51000.0,
        quantity=0.002,
        size_usd=102.0,
        fee=0.6,
        position_id="test_pos_1"
    )

    db.close_position(
        position_id="test_pos_1",
        exit_price=51000.0,
        exit_fee=0.6,
        exit_reason="Take profit hit"
    )

    # Get statistics
    print("\n=== Statistics ===")
    stats = db.get_statistics()
    for key, value in stats.items():
        print(f"{key}: {value}")
