# Execution Path Fixes

## Applied

- Added `bot/pending_order_reconciler.py`.
- Provides `reconcile_stale_pending_orders(...)`.
- Clears terminal pending orders.
- Queries broker order status when supported.
- Cancels stale open/pending orders after timeout.
- Releases symbol locks when stale orders are cleared.
- Emits `STALE_PENDING_ORDER_CLEARED` warning telemetry.

## Required Runtime Wiring

Call the reconciler once at the start of each trading cycle before scanning/submitting new entries:

```python
try:
    from bot.pending_order_reconciler import reconcile_stale_pending_orders
except ImportError:
    from pending_order_reconciler import reconcile_stale_pending_orders  # type: ignore[import]

reconcile_stale_pending_orders(
    owner=self,
    broker=getattr(self.apex, "broker_client", None),
    pending_orders=getattr(self.apex, "pending_orders", None),
    timeout_s=float(os.getenv("NIJA_PENDING_ORDER_TIMEOUT_S", "90")),
)
```

## Environment Changes Required in Railway

```env
MIN_TRADE_USD=50
MIN_CASH_TO_BUY=50
KRAKEN_MIN_NOTIONAL_USD=50
COINBASE_MIN_ORDER_USD=50
OKX_MIN_ORDER_USD=50
NIJA_PENDING_ORDER_TIMEOUT_S=90
```

## Validation

After deploy, confirm these logs:

```text
STALE_PENDING_ORDER_CLEARED
SIGNAL PASSED all gates
BEFORE execute_action
AFTER execute_action
ORDER RESULT
ORDER_SUBMITTED
ORDER_FILLED
```
