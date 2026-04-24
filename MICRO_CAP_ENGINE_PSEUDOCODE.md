# MICRO_CAP Engine Pseudo-Code
## Ultra-Conservative Trading Engine for $20-$100 Accounts

**Philosophy:** Small accounts die from ACTIVITY, not from lack of opportunity.

**Target:** Sustainable growth through deliberate, high-quality entries only.

**Win/Loss Profile:**
- Win: +$0.40 (2% on $20)
- Loss: -$0.20 (1% on $20)
- 2:1 reward-to-risk ratio

---

## 1. INITIALIZATION

```pseudocode
FUNCTION initialize_micro_cap_engine(account_balance):
    
    // Verify account qualifies for MICRO_CAP mode
    IF account_balance < 20.00 OR account_balance > 100.00:
        RETURN error("Account balance must be $20-$100 for MICRO_CAP mode")
    
    // Configuration
    CONFIG = {
        // Account tier
        tier: "MICRO_CAP",
        balance_range: [20.00, 100.00],
        
        // Position constraints
        max_concurrent_positions: 1,        // Only 1 position at a time
        position_size_usd: 20.00,           // Fixed $20 position size
        
        // Risk parameters
        profit_target_pct: 2.0,             // 2% profit target ($0.40)
        stop_loss_pct: 1.0,                 // 1% stop loss ($0.20)
        
        // Entry throttling
        entry_interval_seconds: 30.0,       // 30s between entries
        max_entries_per_minute: 2,          // Max 2 entries/minute
        
        // Exit speed
        exit_interval_seconds: 5.0,         // 5s between exits (fast exits OK)
        
        // Quality filtering
        high_confidence_only: true,         // Only high-confidence signals
        min_quality_score: 0.75,            // Minimum 75% quality score
        
        // Order management
        stale_order_timeout_seconds: 120,   // Cancel orders after 2 minutes
        
        // Anti-patterns (what NOT to do)
        allow_dca: false,                   // No averaging down
        allow_scalping: false,              // No scalping
        allow_high_frequency: false,        // No HFT
        allow_multiple_positions: false,    // No position fragmentation
        allow_momentum_chasing: false,      // No low-quality momentum trades
        allow_auto_reentry: false,          // No automatic re-entry loops
    }
    
    // State tracking
    STATE = {
        current_position: null,             // Currently open position (if any)
        last_entry_time: null,              // Timestamp of last entry
        open_orders: [],                    // List of open orders
        entry_count_this_minute: 0,         // Counter for rate limiting
        minute_window_start: current_time(),
        total_trades_today: 0,
        profitable_trades_today: 0,
    }
    
    RETURN CONFIG, STATE
END FUNCTION
```

---

## 2. MAIN TRADING LOOP

```pseudocode
FUNCTION main_trading_loop():
    
    WHILE bot_is_running:
        
        // Step 1: Cleanup stale orders
        cleanup_stale_orders()
        
        // Step 2: Check and manage existing position
        IF STATE.current_position IS NOT null:
            manage_existing_position()
        
        // Step 3: Scan for new entry opportunities (only if no position)
        ELSE:
            scan_for_entry_opportunities()
        
        // Step 4: Sleep before next iteration
        SLEEP(5 seconds)  // Check every 5 seconds
    
    END WHILE

END FUNCTION
```

---

## 3. ENTRY LOGIC

```pseudocode
FUNCTION scan_for_entry_opportunities():
    
    // GATE 1: Check if we have an open position
    IF STATE.current_position IS NOT null:
        LOG("Skipping entry scan - already have 1 position (max allowed)")
        RETURN false
    
    // GATE 2: Check entry rate limiting
    IF NOT can_enter_new_position():
        LOG("Skipping entry scan - rate limit not satisfied")
        RETURN false
    
    // GATE 3: Scan markets for signals
    signals = scan_all_markets_for_signals()
    
    IF signals IS empty:
        LOG("No signals found")
        RETURN false
    
    // GATE 4: Filter for high-confidence signals only
    high_confidence_signals = FILTER signals WHERE:
        signal.quality_score >= CONFIG.min_quality_score (0.75)
        AND signal.confidence == "HIGH"
    
    IF high_confidence_signals IS empty:
        LOG("No high-confidence signals found (all below 75% threshold)")
        RETURN false
    
    // GATE 5: Select best signal
    best_signal = SELECT TOP 1 FROM high_confidence_signals
                  ORDER BY quality_score DESC
    
    LOG("High-confidence signal found:", best_signal.symbol, 
        "Quality:", best_signal.quality_score)
    
    // GATE 6: Validate entry conditions
    IF NOT validate_entry_conditions(best_signal):
        LOG("Entry validation failed for", best_signal.symbol)
        RETURN false
    
    // EXECUTE ENTRY
    execute_entry(best_signal)
    
    RETURN true

END FUNCTION


FUNCTION can_enter_new_position():
    
    current_time = NOW()
    
    // Check if 30 seconds have passed since last entry
    IF STATE.last_entry_time IS NOT null:
        time_since_last_entry = current_time - STATE.last_entry_time
        
        IF time_since_last_entry < CONFIG.entry_interval_seconds (30):
            RETURN false
    
    // Check per-minute rate limit
    IF current_time - STATE.minute_window_start >= 60 seconds:
        // Reset minute window
        STATE.minute_window_start = current_time
        STATE.entry_count_this_minute = 0
    
    IF STATE.entry_count_this_minute >= CONFIG.max_entries_per_minute (2):
        RETURN false
    
    RETURN true

END FUNCTION


FUNCTION validate_entry_conditions(signal):
    
    // Check account balance
    balance = get_account_balance()
    
    IF balance < CONFIG.position_size_usd (20.00):
        LOG("Insufficient balance for $20 position")
        RETURN false
    
    // Check market conditions
    market_data = get_market_data(signal.symbol)
    
    IF market_data.liquidity_score < 0.7:
        LOG("Market liquidity too low")
        RETURN false
    
    IF market_data.spread_pct > 0.5:
        LOG("Market spread too wide")
        RETURN false
    
    // Check symbol restrictions
    IF signal.symbol IN restricted_symbols:
        LOG("Symbol is restricted")
        RETURN false
    
    RETURN true

END FUNCTION


FUNCTION execute_entry(signal):
    
    LOG("========================================")
    LOG("ENTERING POSITION (MICRO_CAP MODE)")
    LOG("========================================")
    LOG("Symbol:", signal.symbol)
    LOG("Quality Score:", signal.quality_score)
    LOG("Position Size: $20.00")
    LOG("========================================")
    
    // Calculate entry parameters
    current_price = get_current_price(signal.symbol)
    quantity = CONFIG.position_size_usd / current_price  // $20 / price
    
    // Calculate profit target and stop loss
    profit_target_price = current_price * (1 + CONFIG.profit_target_pct / 100)  // +2%
    stop_loss_price = current_price * (1 - CONFIG.stop_loss_pct / 100)         // -1%
    
    LOG("Entry Price:", current_price)
    LOG("Profit Target (2%):", profit_target_price, "(+$0.40)")
    LOG("Stop Loss (1%):", stop_loss_price, "(-$0.20)")
    
    // Place market order
    order_result = place_market_order(
        symbol: signal.symbol,
        side: "BUY",
        quantity: quantity,
        size_type: "quote",  // $20 USD worth
    )
    
    IF order_result.status == "filled":
        
        // Track position
        STATE.current_position = {
            symbol: signal.symbol,
            entry_price: order_result.filled_price,
            quantity: order_result.filled_quantity,
            size_usd: 20.00,
            profit_target_price: profit_target_price,
            stop_loss_price: stop_loss_price,
            entry_time: NOW(),
            quality_score: signal.quality_score,
        }
        
        // Update state
        STATE.last_entry_time = NOW()
        STATE.entry_count_this_minute += 1
        STATE.total_trades_today += 1
        
        LOG("✅ Position opened successfully")
        RETURN true
    
    ELSE:
        LOG("❌ Entry failed:", order_result.error)
        RETURN false

END FUNCTION
```

---

## 4. EXIT LOGIC

```pseudocode
FUNCTION manage_existing_position():
    
    IF STATE.current_position IS null:
        RETURN
    
    position = STATE.current_position
    current_price = get_current_price(position.symbol)
    
    // Calculate current P&L
    current_value = position.quantity * current_price
    pnl_usd = current_value - position.size_usd
    pnl_pct = (pnl_usd / position.size_usd) * 100
    
    LOG_DEBUG("Position:", position.symbol, 
              "P&L: $", pnl_usd, "(", pnl_pct, "%)")
    
    // EXIT CONDITION 1: Profit target hit (2%)
    IF current_price >= position.profit_target_price:
        LOG("🎯 Profit target hit! Exiting at +2% (+$0.40)")
        execute_exit(position, "PROFIT_TARGET", current_price)
        RETURN
    
    // EXIT CONDITION 2: Stop loss hit (1%)
    IF current_price <= position.stop_loss_price:
        LOG("🛑 Stop loss hit! Exiting at -1% (-$0.20)")
        execute_exit(position, "STOP_LOSS", current_price)
        RETURN
    
    // EXIT CONDITION 3: Trailing stop (optional enhancement)
    // Could add trailing stop logic here for profit protection
    
    // Position still within range - hold
    RETURN

END FUNCTION


FUNCTION execute_exit(position, reason, exit_price):
    
    LOG("========================================")
    LOG("EXITING POSITION (MICRO_CAP MODE)")
    LOG("========================================")
    LOG("Symbol:", position.symbol)
    LOG("Reason:", reason)
    LOG("Entry Price:", position.entry_price)
    LOG("Exit Price:", exit_price)
    LOG("========================================")
    
    // Place market sell order
    order_result = place_market_order(
        symbol: position.symbol,
        side: "SELL",
        quantity: position.quantity,
        size_type: "base",  // Sell exact quantity
    )
    
    IF order_result.status == "filled":
        
        // Calculate final P&L
        exit_value = order_result.filled_quantity * order_result.filled_price
        pnl_usd = exit_value - position.size_usd
        pnl_pct = (pnl_usd / position.size_usd) * 100
        
        LOG("Final P&L: $", pnl_usd, "(", pnl_pct, "%)")
        
        // Update statistics
        IF pnl_usd > 0:
            STATE.profitable_trades_today += 1
            LOG("✅ Profitable trade!")
        ELSE:
            LOG("❌ Loss trade")
        
        // Calculate win rate
        win_rate = (STATE.profitable_trades_today / STATE.total_trades_today) * 100
        LOG("Today's Win Rate:", win_rate, "%")
        
        // Clear position
        STATE.current_position = null
        
        LOG("✅ Position closed successfully")
        LOG("========================================")
        
        RETURN true
    
    ELSE:
        LOG("❌ Exit failed:", order_result.error)
        RETURN false

END FUNCTION
```

---

## 5. ORDER MANAGEMENT

```pseudocode
FUNCTION cleanup_stale_orders():
    
    current_time = NOW()
    
    // Get all open orders
    open_orders = get_open_orders()
    
    FOR EACH order IN open_orders:
        
        order_age_seconds = current_time - order.created_time
        
        // Cancel orders older than 2 minutes
        IF order_age_seconds >= CONFIG.stale_order_timeout_seconds (120):
            
            LOG("🗑️ Cancelling stale order:", order.symbol, 
                "Age:", order_age_seconds, "seconds")
            
            cancel_result = cancel_order(order.order_id)
            
            IF cancel_result.success:
                LOG("✅ Stale order cancelled")
            ELSE:
                LOG("❌ Failed to cancel order:", cancel_result.error)
    
    END FOR

END FUNCTION
```

---

## 6. ANTI-PATTERN PREVENTION

```pseudocode
FUNCTION prevent_death_by_activity():
    
    // These checks prevent the behaviors that kill small accounts
    
    // ANTI-PATTERN 1: No scalping (enforced by 30s interval)
    IF time_since_last_entry < 30 seconds:
        REJECT("No scalping - 30s minimum between entries")
    
    // ANTI-PATTERN 2: No high-frequency entries (enforced by rate limit)
    IF entry_count_this_minute >= 2:
        REJECT("No HFT - max 2 entries per minute")
    
    // ANTI-PATTERN 3: No 5+ positions (enforced by max_concurrent_positions)
    IF current_position_count >= 1:
        REJECT("No position fragmentation - max 1 position")
    
    // ANTI-PATTERN 4: No averaging down (enforced by allow_dca flag)
    IF CONFIG.allow_dca == false AND trying_to_add_to_position:
        REJECT("No DCA - no averaging down on losers")
    
    // ANTI-PATTERN 5: No micro momentum chasing (enforced by quality score)
    IF signal.quality_score < 0.75:
        REJECT("No momentum chasing - quality score too low")
    
    // ANTI-PATTERN 6: No auto re-entry loops (enforced by interval + timeout)
    IF same_symbol_as_previous AND time_since_previous_exit < 60 seconds:
        REJECT("No auto re-entry - wait 60s after exit")
    
    RETURN "All anti-pattern checks passed"

END FUNCTION
```

---

## 7. PERFORMANCE TRACKING

```pseudocode
FUNCTION track_performance():
    
    // Daily statistics
    STATS = {
        total_trades: STATE.total_trades_today,
        profitable_trades: STATE.profitable_trades_today,
        win_rate: (profitable_trades / total_trades) * 100,
        
        // Expected value per trade
        avg_win: 0.40,    // $0.40 (2%)
        avg_loss: 0.20,   // $0.20 (1%)
        
        // Calculate expected daily P&L
        expected_daily_pnl: (profitable_trades * 0.40) - 
                           ((total_trades - profitable_trades) * 0.20),
    }
    
    LOG("========================================")
    LOG("MICRO_CAP DAILY PERFORMANCE")
    LOG("========================================")
    LOG("Total Trades:", STATS.total_trades)
    LOG("Profitable:", STATS.profitable_trades)
    LOG("Win Rate:", STATS.win_rate, "%")
    LOG("Expected Daily P&L: $", STATS.expected_daily_pnl)
    LOG("========================================")
    
    RETURN STATS

END FUNCTION
```

---

## 8. COMPLETE FLOW DIAGRAM

```
START
  │
  ├─→ Initialize MICRO_CAP Engine
  │   ├─ Verify $20-$100 balance
  │   ├─ Load configuration
  │   └─ Initialize state
  │
  ├─→ Main Loop (every 5 seconds)
  │   │
  │   ├─→ Cleanup stale orders (>2 minutes)
  │   │
  │   ├─→ Have position?
  │   │   │
  │   │   YES → Manage Position
  │   │   │     ├─ Check profit target (2%) → EXIT if hit
  │   │   │     ├─ Check stop loss (1%) → EXIT if hit
  │   │   │     └─ Hold otherwise
  │   │   │
  │   │   NO → Scan for Entry
  │   │         │
  │   │         ├─ Check rate limit (30s, max 2/min)
  │   │         ├─ Scan markets
  │   │         ├─ Filter for quality ≥75%
  │   │         ├─ Validate conditions
  │   │         └─ ENTER if all gates pass
  │   │
  │   └─→ Sleep 5 seconds
  │
  └─→ Loop continues...
```

---

## 9. EXAMPLE TRADE SEQUENCE

```
TIME    EVENT                           STATE
------  ------------------------------  ---------------------------
00:00   Bot starts                      Balance: $50, Position: None
00:05   Scan markets                    5 signals found
00:05   Filter by quality               1 signal ≥75% (BTC-USD: 82%)
00:05   ENTER BTC-USD                   Position: $20 @ $45,000
        - Profit Target: $45,900 (+2%)
        - Stop Loss: $44,550 (-1%)
00:35   Market moves up                 Current: $45,850 (+1.89%)
00:40   Profit target hit               Current: $45,920 (+2.04%)
00:40   EXIT BTC-USD                    Profit: +$0.41
00:40   Position closed                 Balance: $50.41, Position: None
01:10   Scan markets (30s passed)       Rate limit satisfied
01:10   No quality signals              All signals <75%, skip
01:15   Scan markets                    No signals
02:00   Quality signal found            ETH-USD: 78% confidence
02:00   ENTER ETH-USD                   Position: $20 @ $2,500
02:15   Market moves down               Current: $2,475 (-1%)
02:15   Stop loss hit                   Current: $2,475 (-1%)
02:15   EXIT ETH-USD                    Loss: -$0.20
02:15   Position closed                 Balance: $50.21, Position: None
...

END OF DAY SUMMARY:
Trades: 8
Wins: 5 (+$2.00)
Losses: 3 (-$0.60)
Net P&L: +$1.40
Win Rate: 62.5%
Balance: $51.40
```

---

## 10. KEY SUCCESS FACTORS

1. **Patience Over Activity**
   - Wait 30 seconds between entries
   - Only 2 entries per minute maximum
   - Quality over quantity

2. **Single Position Focus**
   - 100% of attention on one trade
   - No capital fragmentation
   - Clear decision making

3. **High-Confidence Only**
   - 75% minimum quality score
   - No momentum chasing
   - No low-probability trades

4. **Strict Risk Management**
   - Fixed 2:1 reward-to-risk
   - Hard stops at 1%
   - Profit targets at 2%

5. **No Death Traps**
   - No averaging down
   - No auto re-entry loops
   - No high-frequency churn
   - No position fragmentation

**Result:** Sustainable growth through deliberate, disciplined trading.

---

## END PSEUDO-CODE
