# Quick Answer: Is NIJA Connected to Kraken Pro?

## NO ❌

**NIJA is currently connected to Coinbase Advanced Trade, NOT Kraken Pro.**

---

## Current Configuration

| Item | Status |
|------|--------|
| **Active Broker** | Coinbase Advanced Trade |
| **Account** | dantelrharrell@gmail.com |
| **All Trades** | Executed on Coinbase |
| **Kraken Connection** | Not active (code exists but disabled) |

---

## What This Means

- ✅ All buy orders go to Coinbase
- ✅ All sell orders go to Coinbase  
- ✅ Balance checks query Coinbase
- ✅ Position tracking uses Coinbase API
- ❌ Nothing is happening on Kraken

---

## Proof

**File:** `bot/trading_strategy.py` (line 131)

```python
self.broker = CoinbaseBroker()  # ← This is what's running
```

**NOT using:**
```python
self.broker = KrakenBroker()  # ← This would be Kraken
```

---

## Want to Switch to Kraken?

See detailed instructions in: **`KRAKEN_CONNECTION_STATUS.md`**

Or run the status checker:
```bash
python3 check_kraken_connection_status.py
```

---

## Bottom Line

**All trading activity is on your Coinbase account. Kraken is not being used at all, even though the code to support it exists in the repository.**
