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

### Fail-closed Kraken reconciliation (issue #3173)

The 2026-10-17 BABY-USD observation (`quantity=0.00142000`, unknown entry
price) is **not** evidence of a zero-cost purchase. Preserve the quantity and
`reconciliation_required` / `auto_exit_blocked` state until the original
account-scoped acquisition evidence is independently verified. A market mark,
dust classification, or hydrated capital total cannot establish historical basis.

No production data repair, trading, activation, deployment, or test order is
authorized by this procedure. The coding sandbox has no authenticated Kraken
credentials or `/data/trade_ledger.db`; actual basis determinability, unmatched
fills, pending closes, and historical execution proof remain **unverified**.

Operator evidence/review checklist:

1. Before considering any database write, use the existing
   `scripts/nija_trade_ledger_snapshot_v436.py` **backup** command with
   `--source /data/trade_ledger.db` and an absolute `--output-dir`. Invoke the
   script using its absolute path in the production checkout. Preserve its
   manifest, digest, all SQLite tables (including pending closes), pending
   fill evidence, and execution journal. **The v436 archive does NOT include
   account-scoped positions/ and entry_prices/ directory JSON files.** Preserve
   those using the separate v449 account-state snapshot below.
   Inspect missing/unstable companion warnings; a file-only journal may omit
   in-memory events. Copy the archive off-host and run **restore-test** against
   that independent copy with the original `--expected-sha256`. A local backup
   alone is insufficient.
2. From the existing authenticated **platform:kraken** broker, call
   `collect_from_existing_broker` in
   `scripts/nija_kraken_readonly_history_collector_v441.py` with
   `account_scope="platform:kraken"`, the runtime's monitoring request category,
   and `include_balance=True`. This reuses account routing, private-call nonce
   and rate controls; it only reads Balance, TradesHistory, ClosedOrders and
   Ledgers. Balance reads bracket two full history passes. API failure,
   pagination truncation, or changing evidence invalidates collection.
   Repeat-read consistency does not prove an atomic exchange snapshot or
   independently authenticate account ownership.
3. Retain the evidence hash and exact BABY trade/order IDs, timestamps, pair and
   quote currency, quantities, costs, fees/fee assets, and linked ledger IDs.
   Compare current BABY balance with the full inventory history, including
   sales, transfers, rewards and fees. Record whether basis is determinable and
   why; missing opening fills, unexplained quantity changes, mixed quotes or
   unsupported ledger links must remain unresolved. Never substitute a current
   price, divide unrelated historical cost by current quantity, or delete the
   holding to make reconciliation pass.
4. Compare the verified backup's open positions, ledger fills, pending closes
   and pending-fill evidence using exact broker/account/order provenance.
   Legacy `open_positions` rows do not contain a broker column: matching only
   symbol/user/side is insufficient. The existing offline CSV audit can triage
   pending closes but does not certify authenticated provenance, entry basis or
   realized P&L. Preserve unmatched evidence and prevent duplicate booking.
   Any eventual write requires separate approval, a reviewed per-row change
   plan, independent before/after audit records and verified backups.
5. For capital, compare the **same refresh** result's valid contributor count
   against all three registered platform brokers, independently of connectivity
   and the displayed hydrated total (approximately $758.62 in the incident).
   Require an accepted, non-stale publication and complete current authority
   data. v270 retains missing broker instances in the denominator and reports
   `publication_current` on fail-closed results. Do not reduce the denominator,
   extend freshness, or treat an earlier complete result as the current one.
6. Assess execution proof separately using genuine historical, account-scoped
   broker order/fill events and their original execution timestamps. Compare
   exact identities and existing canonical verifier results; old historical
   evidence may help reconciliation without satisfying current proof freshness.
   `verification_stale` stays a denial. Never stamp history with collection
   time, manufacture a marker, place a probe/test order, or relax kill-switch,
   nonce, protective-exit or execution-proof gates.

### Account-scoped recovery evidence (v449; read-only)

A SQLite snapshot alone does **not** preserve the registered platform/user account
JSON directories. Issue #3024 documents that `/app/data` was observed to resolve
to the `/data` mount on October 11, but current paths, integrity and restart
durability must be verified in the **current live instance** before any redeploy.

Run only from an authorized Render owner shell with the current checkout,
with no new trades, restarts, or state changes. **The current trading deployment
may predate v449**; do not restart/redeploy it merely to make this tool
available. After independent review, transfer the exact approved/pinned v449
script to a private temporary path on the existing live instance by an
authorized secure method, and verify its source hash before running it.
The following creates two **local, private** archives under `/tmp`, and does
not itself copy either archive off-host:

```bash
cd /app
python -S scripts/nija_state_store_persistence_audit_v441.py \
  --persistent-root /data --ledger /data/trade_ledger.db \
  --positions-dir /app/data/positions --entry-prices-dir /app/data/entry_prices
python -S scripts/nija_trade_ledger_snapshot_v436.py backup \
  --source /data/trade_ledger.db --output-dir /tmp/nija-recovery-private
python -S /tmp/approved-nija-account-state-v449.py snapshot \
  --persistent-root /data \
  --positions-dir /app/data/positions --entry-prices-dir /app/data/entry_prices \
  --output-dir /tmp/nija-recovery-private
```

The account-state archive rejects unexpected names, symlinks, non-object JSON,
NaN/Infinity, untrusted paths, size overflows, and changing files. It records
per-member SHA-256 and returns the archive SHA-256; the archive contains private
position information and must be handled as sensitive. **Do not print archive
contents or upload the archive to a public issue or GitHub Actions artifact.**

Transfer each archive through an approved encrypted channel to a restricted
**independent off-host** location. Record the exact SHA-256 from the originating
host and then run these on an isolated verification machine against the copied
archives (replace placeholders with actual verified paths and hashes):

```bash
python -S scripts/nija_trade_ledger_snapshot_v436.py restore-test \
  --archive /restricted/offhost/trading-ledger.tar.gz \
  --expected-sha256 ORIGINAL_LEDGER_SHA256
python -S scripts/nija_account_state_offhost_evidence_v449.py verify \
  --archive /restricted/offhost/account-state.zip \
  --expected-sha256 ORIGINAL_ACCOUNT_SHA256
```

Even if both passes succeed, the snapshots are not **cross-store atomic**:
compare capture timestamps, all original hashes, current authoritative
per-account broker positions, executed trades, pending closes, and exchange
protective exits. Neither script certifies independent off-host custody by
itself, authenticates Kraken ownership, reconstructs BABY historical basis, or
permits LIVE_ACTIVE execution. Retain a separate signed operational attestation
of transfer, isolated restore, identity/reconciliation and rollback review.

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

**Production warning:** Do not use a raw `cp` of a running SQLite database.
NIJA uses WAL-mode SQLite; raw file copying can omit committed changes in
`-wal` files, yield an inconsistent snapshot, and falsely certify recovery.

From an authenticated shell **inside the existing running Render trading
instance** (never a separate Render job, build, or pre-deploy instance), first
confirm the current database path and mount, then use the existing v436
SQLite online-backup implementation:

```bash
cd /app
python -S scripts/nija_ledger_evidence_v438.py --ledger /data/trade_ledger.db
python -S scripts/nija_trade_ledger_snapshot_v436.py backup \
  --source /data/trade_ledger.db \
  --output-dir /tmp/nija-recovery-private
```

The command above creates a **local** backup only. Transfer the generated
archive through approved encrypted transport to restricted independent
off-host storage and compare its exact source SHA-256 with the received
copy. Run `restore-test` on an isolated host:

```bash
python -S scripts/nija_trade_ledger_snapshot_v436.py restore-test \
  --archive /restricted/offhost/nija-trading-ledger-snapshot.tar.gz \
  --expected-sha256 ORIGINAL_SOURCE_SHA256
```

Preserve separately the current account-scoped JSON position and entry-price
state using the vetted v449/v447 procedures in this README. Verify the current
ledger and JSON evidence against authenticated broker records before any
write, restart, deploy, trade, or protective-exit modification. A successful
SQLite integrity check or backup **does not** prove historical cost basis,
cross-store consistency, broker identity, or permission to trade.

The read-only `scripts/nija_offline_archive_reconciliation_audit_v460.py`
can check an **old historical** off-host recovery bundle against an operator
CSV crosswalk, but cannot certify brokerage authenticity or the current
production ledger. An archived match is not a release gate.

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
