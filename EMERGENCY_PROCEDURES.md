# Emergency Procedures

Use these steps to immediately stop bleeding, liquidate all crypto to cash, and prevent the bot from opening new positions until a review is complete.

## Trading Lock

- File: TRADING_LOCKED.conf
- Behavior: When present, bot/trading_strategy.py detects the lock and exits the trading cycle, preventing new positions.
- Flags contained:
  - TRADING_DISABLED=true
  - ALLOW_NEW_POSITIONS=false
  - EMERGENCY_STOP=true
- Why: Ensures no automated trades occur after an emergency liquidation.

## Immediate Actions

1. Liquidate all crypto positions:

```bash
python3 auto_liquidate_now.py
```

2. (Optional) Force-sell with detailed debug output:

```bash
python3 force_sell_debug.py
```

3. Verify liquidation and current balances:

```bash
python3 verify_liquidation.py
python3 final_check.py
python3 final_check_save.py  # also writes bleeding_status.txt
```

4. Confirm the bot is not running and lock is active:

```bash
python3 check_bot_status_secure.py
cat TRADING_LOCKED.conf
```

## Re‑Enable Trading (Only after review)

- Prechecks:
  - Review logs in nija.log and recent trades.
  - Backtest or paper trade any strategy changes.
- Remove the trading lock:

```bash
rm TRADING_LOCKED.conf
```

- Restart the bot via your normal start method and monitor logs.

## Safety Notes

- Do not remove TRADING_LOCKED.conf until all verification steps pass.
- Never commit secrets: keep .env local; do not push keys.
- Coinbase API can rate‑limit; expect brief delays and use the verification scripts above.
