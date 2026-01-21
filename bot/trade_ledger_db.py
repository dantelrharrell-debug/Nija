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
                    user_id TEXT DEFAULT 'master',
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    action TEXT NOT NULL,
                    price REAL NOT NULL,
                    quantity REAL NOT NULL,
                    size_usd REAL NOT NULL,
                    fee REAL DEFAULT 0.0,
                    order_id TEXT,
                    position_id TEXT,
                    notes TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Open positions table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS open_positions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    position_id TEXT UNIQUE NOT NULL,
                    user_id TEXT DEFAULT 'master',
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
                    user_id TEXT DEFAULT 'master',
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
            
            logger.info("✅ Database schema initialized")
    
    def record_buy(self, symbol: str, price: float, quantity: float, 
                   size_usd: float, fee: float = 0.0, 
                   order_id: str = None, position_id: str = None,
                   user_id: str = 'master', notes: str = None) -> int:
        """
        Record a BUY transaction in the ledger
        
        Returns:
            Transaction ID
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO trade_ledger 
                (timestamp, user_id, symbol, side, action, price, quantity, 
                 size_usd, fee, order_id, position_id, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                notes
            ))
            
            tx_id = cursor.lastrowid
            logger.info(f"📝 BUY recorded: {symbol} @ ${price:.2f} (ID: {tx_id})")
            return tx_id
    
    def record_sell(self, symbol: str, price: float, quantity: float, 
                    size_usd: float, fee: float = 0.0,
                    order_id: str = None, position_id: str = None,
                    user_id: str = 'master', notes: str = None) -> int:
        """
        Record a SELL transaction in the ledger
        
        Returns:
            Transaction ID
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO trade_ledger 
                (timestamp, user_id, symbol, side, action, price, quantity, 
                 size_usd, fee, order_id, position_id, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                notes
            ))
            
            tx_id = cursor.lastrowid
            logger.info(f"📝 SELL recorded: {symbol} @ ${price:.2f} (ID: {tx_id})")
            return tx_id
    
    def open_position(self, position_id: str, symbol: str, side: str,
                     entry_price: float, quantity: float, size_usd: float,
                     stop_loss: float = None, take_profit_1: float = None,
                     take_profit_2: float = None, take_profit_3: float = None,
                     entry_fee: float = 0.0, user_id: str = 'master',
                     notes: str = None) -> bool:
        """
        Record a new open position
        
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
                     take_profit_3, entry_fee, entry_time, notes)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    notes
                ))
                
                logger.info(f"📈 Position opened: {symbol} {side} (ID: {position_id})")
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
                
                if side.upper() == 'LONG' or side.upper() == 'BUY':
                    gross_profit = exit_value - size_usd
                else:  # SHORT or SELL
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
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            query = f"SELECT * FROM {table} WHERE 1=1"
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
