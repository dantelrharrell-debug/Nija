# NIJA trading-ledger recovery (v436) — operator action required

**No new live trading, disk mount, or deployment until the current live SQLite ledger is backed up off the container.** Render reported `ephemeral_filesystem` and `disk=null`. Code pushed to this branch does not change production.

## 1. Preserve the current instance
Open the [trading service in Render](https://dashboard.render.com/web/srv-d98dsr5aeets73fpbaqg) and open its current running-instance shell. Confirm the current working directory, `NIJA_TRADE_LEDGER_DB_PATH`, the ledger's presence and nonzero size, and whether it has a SQLite WAL. Do not share private credentials or raw ledger data in chat. A read-only snapshot utility is staged at `scripts/nija_trade_ledger_snapshot_v436.py` on this branch. **Do not deploy the branch merely to make the utility available.** Transfer that single script into the existing live container using a secure approved operator mechanism, or execute the equivalent verified SQLite online backup in the shell.

Example on the **current** instance once the utility is available:

```bash
python scripts/nija_trade_ledger_snapshot_v436.py backup --source ./data/trade_ledger.db --output-dir /tmp/nija-recovery
```

The utility reads the source with SQLite's backup API, validates `PRAGMA integrity_check`, counts tables, includes the pending-fill registry and journal if present, and writes a SHA-256 manifest. A snapshot can be valid yet incomplete if companion files are missing or changed during copying; check `companions_stable` and `missing_companions`. A local `/tmp` archive is **not** a durable backup. Transfer it to secure off-host storage with encrypted transport, verify the checksum and archive there, then perform an isolated restore test before modifying the service.

```bash
python scripts/nija_trade_ledger_snapshot_v436.py verify --archive /path/to/offhost-copy.tar.gz
```

## 2. Restore durable trading storage
Use an authorized Render operator to attach a **persistent trading disk** to the service or provision an isolated transactional trading database. Do not reuse the billing Postgres instance. Because a new disk mounts an empty filesystem and triggers deployment, confirm the off-host backup and restore method **before** attaching it. Restore the database and pending evidence to the intended mount, verify SQLite integrity, counts and WAL consistency, then point `NIJA_TRADE_LEDGER_DB_PATH` at the restored ledger. Confirm the process UID can access the mount and a controlled restart retains the data.

## 3. Reconcile actual Kraken fills
The pending close audit has independently confirmed unmatched `platform:kraken` exits, including `OSW7F3-YD2NX-SR3BZB`, `O65MOF-36V4S-6DON6C`, and `OXKYEI-7ZOTF-WQNU5Z`. Read Kraken private QueryOrders/TradesHistory for each **exact** account and order. For each historical close, match the actual acquisition/position opening by exact account, position, symbol, side, filled quantity, costs, and fees. A same-symbol trade is not sufficient. If the source ledger is already lost, do not manufacture opening fills, cost basis, or P&L; record the missing history as unproven.

## 4. Fresh execution and strategy performance
Freshness means a **new actual authenticated exchange execution event**, not a replayed old order or a newly observed position. Keep `EXECUTION_ALLOWED=false` until normal policy can verify the requisite proof. Do not force a heartbeat order, clear a stop, or relax risk thresholds to manufacture it. Strategy win/loss reporting requires exact strategy-to-order-to-fill-to-completed-trade joins, and historical unmatched entries remain unattributed.

## Release evidence checklist
- [ ] Verified off-host backup and isolated restore test of all existing trade-ledger data
- [ ] Dedicated trading store mounted and durable across a controlled restart
- [ ] Broker position/spot balance and protective exit truth for every account
- [ ] Authenticated exact Kraken entries and exits reconciled, or explicitly unproven
- [ ] Execution proof fresh within the real 1,800-second policy window
- [ ] Strategy-level P&L attributable to exact completed trades
- [ ] All CI checks passed; safety reviewer approves production deployment

This runbook and utility are **not proof of completion**. Preserve protective exits and emergency stops.
