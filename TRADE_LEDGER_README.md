# Trade Ledger Database Documentation

## Overview

The NIJA Trading Bot now includes a comprehensive trade ledger system that records every BUY/SELL transaction in a persistent SQLite database. This system provides:

- **Complete Trade History**: Every transaction is logged with full details
- **Open Positions Tracking**: Real-time view of all active positions
- **Performance Analytics**: Win rate, P&L, and detailed statistics
- **Data Export**: CSV export functionality for all data
- **REST API**: Full API access to trade data
- **Web Dashboard**: Beautiful UI for viewing trades and positions

## Database Schema

### Tables

#### `trade_ledger`
Records every individual BUY/SELL transaction:
- `id`: Unique transaction ID
- `timestamp`: Transaction timestamp
- `user_id`: User identifier (default: 'master')
- `symbol`: Trading pair (e.g., 'BTC-USD')
- `side`: 'BUY' or 'SELL'
- `action`: 'OPEN' or 'CLOSE'
- `price`: Execution price
- `quantity`: Asset quantity
- `size_usd`: Position size in USD
- `fee`: Transaction fee
- `order_id`: Broker order ID
- `position_id`: Unique position identifier
- `notes`: Additional notes

#### `open_positions`
Tracks currently open positions:
- `position_id`: Unique position identifier
- `user_id`: User identifier
- `symbol`: Trading pair
- `side`: 'LONG' or 'SHORT'
- `entry_price`: Entry price
- `quantity`: Position quantity
- `size_usd`: Position size in USD
- `stop_loss`: Stop loss price
- `take_profit_1/2/3`: Take profit levels
- `entry_fee`: Entry transaction fee
- `entry_time`: Position open timestamp
- `status`: Position status

#### `completed_trades`
Historical completed trades with P&L:
- `position_id`: Unique position identifier
- `user_id`: User identifier
- `symbol`: Trading pair
- `side`: 'LONG' or 'SHORT'
- `entry_price`: Entry price
- `exit_price`: Exit price
- `quantity`: Position quantity
- `size_usd`: Position size in USD
- `entry_fee`: Entry transaction fee
- `exit_fee`: Exit transaction fee
- `total_fees`: Combined fees
- `gross_profit`: Profit before fees
- `net_profit`: Profit after fees
- `profit_pct`: Profit percentage
- `entry_time`: Entry timestamp
- `exit_time`: Exit timestamp
- `duration_seconds`: Trade duration
- `exit_reason`: Reason for exit

## API Endpoints

All endpoints are available at `http://localhost:5001/api/`

### Open Positions

```bash
GET /api/positions/open
```

**Query Parameters:**
- `user_id` (optional): Filter by user ID
- `symbol` (optional): Filter by trading symbol

**Response:**
```json
{
  "positions": [
    {
      "position_id": "BTC-USD_1705858800",
      "symbol": "BTC-USD",
      "side": "LONG",
      "entry_price": 50000.0,
      "quantity": 0.002,
      "size_usd": 100.0,
      "stop_loss": 49000.0,
      "take_profit_1": 51000.0,
      "entry_time": "2026-01-21T10:00:00",
      "user_id": "master"
    }
  ],
  "count": 1,
  "timestamp": "2026-01-21T16:30:00"
}
```

### Trade History

```bash
GET /api/trades/history
```

**Query Parameters:**
- `user_id` (optional): Filter by user ID
- `symbol` (optional): Filter by trading symbol
- `limit` (optional): Max results (default: 100)
- `offset` (optional): Pagination offset

**Response:**
```json
{
  "trades": [
    {
      "position_id": "ETH-USD_1705858700",
      "symbol": "ETH-USD",
      "side": "LONG",
      "entry_price": 3000.0,
      "exit_price": 3100.0,
      "size_usd": 100.0,
      "net_profit": 2.79,
      "profit_pct": 2.79,
      "duration_seconds": 1800,
      "exit_reason": "Take profit",
      "exit_time": "2026-01-21T10:30:00"
    }
  ],
  "count": 1,
  "statistics": {
    "total_trades": 10,
    "total_pnl": 45.67,
    "win_rate": 70.0,
    "winners": 7,
    "losers": 3
  },
  "timestamp": "2026-01-21T16:30:00"
}
```

### Raw Transaction Ledger

```bash
GET /api/trades/ledger
```

**Query Parameters:**
- `user_id` (optional): Filter by user ID
- `symbol` (optional): Filter by trading symbol
- `limit` (optional): Max results (default: 100)

**Response:**
```json
{
  "transactions": [
    {
      "id": 1,
      "timestamp": "2026-01-21T10:00:00",
      "symbol": "BTC-USD",
      "side": "BUY",
      "action": "OPEN",
      "price": 50000.0,
      "quantity": 0.002,
      "size_usd": 100.0,
      "fee": 0.6,
      "user_id": "master"
    }
  ],
  "count": 1
}
```

### Statistics

```bash
GET /api/trades/statistics
```

**Query Parameters:**
- `user_id` (optional): Filter by user ID

**Response:**
```json
{
  "statistics": {
    "total_trades": 10,
    "total_pnl": 45.67,
    "avg_pnl": 4.567,
    "winners": 7,
    "losers": 3,
    "best_trade": 15.23,
    "worst_trade": -8.45,
    "total_fees": 12.00,
    "open_positions": 2,
    "win_rate": 70.0
  },
  "user_id": "master",
  "timestamp": "2026-01-21T16:30:00"
}
```

### Export Data

```bash
GET /api/trades/export
```

**Query Parameters:**
- `format`: 'csv' or 'pdf' (CSV only currently supported)
- `table`: 'trade_ledger', 'open_positions', or 'completed_trades'
- `user_id` (optional): Filter by user ID

**Response:**
Downloads a CSV file with the requested data.

**Example:**
```bash
curl "http://localhost:5001/api/trades/export?format=csv&table=completed_trades" -o trades.csv
```

## Web Dashboard

Access the trade ledger dashboard at:
```
http://localhost:5000/trades
```

### Features

1. **Statistics Overview**
   - Total trades count
   - Win rate percentage
   - Total P&L
   - Open positions count
   - Total fees paid
   - Best trade performance

2. **Three Tabs:**
   - **Open Positions**: View all active positions with entry details
   - **Trade History**: Completed trades with P&L metrics
   - **Raw Ledger**: All BUY/SELL transactions

3. **Filters**
   - Filter by symbol
   - Filter by user ID

4. **Export**
   - One-click CSV export for each tab
   - Export buttons on each view

5. **Auto-Refresh**
   - Dashboard auto-refreshes every 30 seconds
   - Real-time updates

## Integration with Execution Engine

The trade ledger is automatically integrated into the execution engine:

```python
from bot.execution_engine import ExecutionEngine
from bot.broker_manager import BrokerManager

# Initialize
broker = BrokerManager()
engine = ExecutionEngine(broker_client=broker, user_id='master')

# Execute a trade - automatically recorded in database
position = engine.execute_entry(
    symbol='BTC-USD',
    side='long',
    position_size=100.0,
    entry_price=50000.0,
    stop_loss=49000.0,
    take_profit_levels={'tp1': 51000.0, 'tp2': 52000.0, 'tp3': 53000.0}
)

# Close position - automatically recorded
engine.execute_exit(
    symbol='BTC-USD',
    exit_price=51000.0,
    size_pct=1.0,
    reason='Take profit hit'
)
```

## Database Location

By default, the database is stored at:
```
./data/trade_ledger.db
```

You can specify a different location:

```python
from bot.trade_ledger_db import get_trade_ledger_db

db = get_trade_ledger_db('/custom/path/trade_ledger.db')
```

## Programmatic Access

### Python Examples

```python
from bot.trade_ledger_db import get_trade_ledger_db

# Get database instance
db = get_trade_ledger_db()

# Get open positions
positions = db.get_open_positions(user_id='master')
for pos in positions:
    print(f"{pos['symbol']}: ${pos['size_usd']:.2f} @ ${pos['entry_price']:.2f}")

# Get trade history
trades = db.get_trade_history(limit=10)
for trade in trades:
    print(f"{trade['symbol']}: ${trade['net_profit']:.2f} ({trade['profit_pct']:.2f}%)")

# Get statistics
stats = db.get_statistics()
print(f"Win Rate: {stats['win_rate']:.1f}%")
print(f"Total P&L: ${stats['total_pnl']:.2f}")

# Export to CSV
csv_data = db.export_to_csv('completed_trades')
with open('trades_export.csv', 'w') as f:
    f.write(csv_data)
```

## Security & Privacy

- Database files should not be committed to version control
- Add to `.gitignore`: `data/trade_ledger.db`
- API endpoints should be protected with authentication in production
- Consider encryption for sensitive trade data

## Backup & Maintenance

### Backup Database

```bash
# Create backup
cp data/trade_ledger.db data/trade_ledger_backup_$(date +%Y%m%d).db

# Or use SQLite backup command
sqlite3 data/trade_ledger.db ".backup data/trade_ledger_backup.db"
```

### Database Maintenance

```python
from bot.trade_ledger_db import get_trade_ledger_db

db = get_trade_ledger_db()

# Get database statistics
stats = db.get_statistics()
print(f"Total trades: {stats['total_trades']}")

# Note: Database is automatically optimized with indexes
# No manual maintenance required
```

## Performance Considerations

- All tables have indexes on frequently queried columns
- Database uses SQLite's WAL mode for better concurrency
- Queries are optimized with proper WHERE clauses
- Large exports may take time - use pagination for API queries

## Troubleshooting

### Database locked error
If you get "database is locked" errors:
1. Ensure only one process is writing at a time
2. Check for long-running transactions
3. Increase timeout in connection settings

### Missing data
If trades aren't appearing:
1. Check execution_engine is initialized with trade_ledger enabled
2. Verify database file permissions
3. Check logs for database write errors

### API not responding
1. Ensure Flask server is running: `python bot/user_dashboard_api.py`
2. Check port 5001 is not blocked
3. Verify trade_ledger_db module is importable

## Future Enhancements

- PDF export functionality
- Advanced filtering (date ranges, profit ranges)
- Trade performance charts and graphs
- Real-time WebSocket updates
- Multi-currency support
- Tax reporting exports
- Trade journaling and notes

## Support

For issues or questions:
1. Check the logs in `./logs/`
2. Verify database integrity with SQLite tools
3. Consult NIJA documentation
4. Open an issue on GitHub

---

**Last Updated:** January 21, 2026
**Version:** 1.0
**Author:** NIJA Trading Systems
