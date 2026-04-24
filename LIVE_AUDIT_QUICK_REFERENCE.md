# Live Balance Audit - Quick Reference

## Audit Commands

### 1. Quick Configuration Check
```bash
cd /home/runner/work/Nija/Nija
python bot/comprehensive_audit.py
```

**What it checks:**
- ✅ MICRO_CAP mode is ACTIVE
- ✅ DCA is DISABLED
- ✅ Multiple entries DISABLED
- ✅ Position limits (4 max)
- ✅ Min trade size ($5)
- ✅ Order tracker state
- ✅ Performance tracker state

**Expected Output:**
```
✅ AUDIT PASSED: System is properly configured and hardened

Key Findings:
• MICRO_CAP mode is active with proper restrictions
• DCA is disabled (prevents averaging down)
• Multiple entries on same symbol disabled (prevents fragmentation)
```

---

### 2. Live Balance Verification (When Connected)
```bash
python bot/live_balance_audit.py
```

**What it shows:**
```
For each account:
   Total Balance:        $XXX.XX
   Available:            $XXX.XX
   Held in Positions:    $XX.XX
   Held in Orders:       $XX.XX
   ────────────────────────────────
   Total Held:           $XX.XX

   Open Positions:       X
   Open Orders:          X

✅ MICRO_CAP COMPLIANCE:
   If held capital aligns with 1-4 positions of ~$5-20 each = COMPLIANT
   If fragmented across many small orders = NON-COMPLIANT
```

---

## Reality Check Results

### ✅ Configuration Audit Results (Just Run)

**MICRO_CAP Configuration:**
- Mode: ✅ ACTIVE
- MAX_POSITIONS: 4 ✅
- ENABLE_DCA: ❌ DISABLED ✅ (correct)
- ALLOW_MULTIPLE_ENTRIES_SAME_SYMBOL: ❌ DISABLED ✅ (correct)
- MIN_TRADE_SIZE: $5.00 ✅

**Hardening Verification:**
- ✅ DCA is properly DISABLED (prevents averaging down)
- ✅ Multiple entries properly DISABLED (prevents fragmentation)
- ✅ MAX_POSITIONS is appropriate: 4
- ✅ MIN_TRADE_SIZE is reasonable: $5.00

**Verdict:** ✅ **CONFIGURATION IS HARDENED**

---

## What to Look For

### ✅ GOOD (Hardened)
```
Account: PLATFORM
   Total Balance:        $100.00
   Held in Positions:    $20.00    ← Single position
   Held in Orders:       $0.00     ← No pending orders
   Total Held:           $20.00    ← 20% of balance
   
   Open Positions:       1         ← One position
   Open Orders:          0         ← No fragmentation

✅ MICRO_CAP COMPLIANCE: COMPLIANT
```

### ❌ BAD (Fragmented)
```
Account: PLATFORM
   Total Balance:        $100.00
   Held in Positions:    $5.00     ← Many small positions
   Held in Orders:       $35.00    ← Multiple pending orders
   Total Held:           $40.00    ← 40% of balance locked up
   
   Open Positions:       3         ← Multiple positions
   Open Orders:          7         ← Fragmentation!

❌ MICRO_CAP COMPLIANCE: NON-COMPLIANT
   ⚠️ ORDER FRAGMENTATION DETECTED: 40% of capital held across 7 orders
```

---

## Interpretation Guide

### Total Held Capital
**For MICRO_CAP accounts ($15-$500):**
- ✅ **Good:** $5-$80 held (single position of $20 or less)
- ⚠️ **Warning:** $80-$150 held (multiple positions, but not fragmented)
- ❌ **Bad:** >$150 held OR >30% of balance (fragmentation)

### Order Count
- ✅ **Good:** 0-4 orders (clean, focused)
- ⚠️ **Warning:** 5-6 orders (borderline)
- ❌ **Bad:** 7+ orders (fragmentation)

### Position Count
- ✅ **Good:** 1-2 positions (focused trading)
- ⚠️ **Warning:** 3-4 positions (max allowed)
- ❌ **Bad:** 5+ positions (should be impossible with MAX_POSITIONS=4)

---

## Action Items Based on Results

### If Configuration Audit Fails
1. Check `bot/micro_capital_config.py`
2. Verify `ENABLE_DCA = False`
3. Verify `ALLOW_MULTIPLE_ENTRIES_SAME_SYMBOL = False`
4. Restart system to load new config

### If Live Balance Shows Fragmentation
1. **Cancel stale orders:**
   ```python
   from bot.account_order_tracker import get_order_tracker
   tracker = get_order_tracker()
   tracker.cleanup_stale_orders(account_id, force_cancel=True)
   ```

2. **Close smallest positions:**
   - Keep 1-2 largest positions
   - Exit dust positions (<$10)

3. **Wait before new entries:**
   - Don't place new orders until held capital < 30%

### If Accounts Are Mixed
1. **Verify separation:**
   ```python
   from bot.account_performance_tracker import get_performance_tracker
   tracker = get_performance_tracker()
   results = tracker.verify_no_aggregation()
   print(results)
   ```

2. If contamination found:
   - Check trade recording code
   - Verify account_id is passed correctly
   - May need to reset performance state

---

## Monitoring Schedule

### Daily (If Trading Active)
- Run `comprehensive_audit.py` before market open
- Verify configuration hasn't changed

### Per Trade (If Using Live System)
- Check held capital after each order
- Verify fragmentation threshold not exceeded

### Weekly
- Run `live_balance_audit.py` for full verification
- Review performance metrics per account
- Check for stale orders

---

## Quick Troubleshooting

### "No order tracker state found"
- ✅ **Normal** if system hasn't placed orders yet
- Not an error, just means clean state

### "Could not get PLATFORM balance"
- Broker not connected (needs credentials)
- Run audit tools to verify configuration instead

### "MICRO_CAP mode not active"
- Check `bot/micro_capital_config.py`
- Verify `MICRO_CAPITAL_MODE = True`

### "Fragmentation detected"
- Cancel stale orders
- Close smallest positions
- Wait before new entries

---

## Files Reference

### Audit Tools
- `bot/comprehensive_audit.py` - Configuration verification
- `bot/live_balance_audit.py` - Live balance check (needs broker connection)

### Tracking Systems
- `bot/account_order_tracker.py` - Order tracking per account
- `bot/account_performance_tracker.py` - Performance tracking per account

### Configuration
- `bot/micro_capital_config.py` - MICRO_CAP settings

### Tests
- `bot/tests/test_order_management.py` - Order management tests
- `bot/tests/test_account_performance.py` - Performance tracking tests

---

## Expected Baseline (Clean State)

```
COMPREHENSIVE BALANCE & CONFIGURATION AUDIT

✅ Configuration: PASSED
   • MICRO_CAP mode ACTIVE
   • DCA DISABLED
   • Multiple entries DISABLED
   • MAX_POSITIONS: 4

✅ Order Tracker: PASSED
   • No tracked orders (clean)
   • No held capital

✅ Performance Tracker: PASSED
   • No performance files yet (no trades)

✅ Overall: SYSTEM IS HARDENED
```

This is the expected state if:
- System just started
- No trades placed yet
- Configuration is correct

---

## Summary

**Configuration Status:** ✅ **HARDENED AND VERIFIED**

The comprehensive audit confirms:
1. ✅ MICRO_CAP mode is ACTIVE
2. ✅ DCA is DISABLED (no averaging down)
3. ✅ Multiple entries DISABLED (no fragmentation)
4. ✅ Position limits appropriate (max 4)
5. ✅ Order tracking operational
6. ✅ Performance tracking operational

**Next Steps:**
1. Run `live_balance_audit.py` when broker is connected
2. Verify held capital aligns with single $20 position
3. Monitor for order fragmentation
4. Use audit tools regularly to verify reality

**Status:** ✅ Ready for production with verification tools
