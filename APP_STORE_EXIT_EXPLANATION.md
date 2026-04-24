# App Store: "How Exits Work" - Final Copy

## For App Review Submission

### Product Description Section - Exit Strategy Explanation

**How Profit-Taking and Risk Management Work**

NIJA uses intelligent automated exits to help protect your capital and capture profits. Here's how the system manages your positions:

**Automatic Exit Logic** - Every trading position is monitored continuously (every 2.5 minutes) for exit opportunities. The system checks multiple conditions to determine the optimal exit time:

• **Profit Targets**: Positions automatically close when they reach profitable levels (typically 2-5% gains depending on your account size and exchange fees). Smaller accounts use tighter targets to build capital faster, while larger accounts can afford to wait for bigger wins.

• **Stop-Loss Protection**: If a position moves against you, the system limits losses (typically 0.5-1% maximum loss). This protects your capital from significant drawdowns and ensures you can continue trading.

• **Trailing Stops**: When a position is profitable, the system automatically raises the stop-loss to lock in gains as the price moves in your favor. This lets winning trades run while protecting accumulated profits.

• **Time-Based Exits**: Positions that remain open too long without hitting profit or stop targets may be closed to free capital for new opportunities.

**Position Adoption** - If the app restarts for any reason (updates, maintenance, or system issues), it automatically scans your exchange account and "adopts" any existing open positions. This means exit logic is immediately reattached to all positions, ensuring your stop-losses and profit targets remain active even after a restart. You're never left with unmanaged positions.

**Independent Account Management** - Each connected exchange account (whether your main trading account or additional accounts) operates independently with identical exit rules. Your Kraken account, Coinbase account, and any other accounts all use the same proven strategy, but they don't affect each other. This means if one exchange has technical issues, your other accounts continue trading normally.

**Emergency Controls** - You maintain full control at all times. You can manually close positions through your exchange's app, pause new trades, or activate emergency liquidation if needed. The system is designed to assist your trading decisions, not replace your judgment.

**Educational Transparency** - All exit decisions are logged with clear explanations ("Profit target +3.0% hit", "Stop-loss triggered at -0.8%", etc.) so you can learn from each trade and understand exactly why positions were closed.

---

## For In-App Help/Documentation

### "Understanding Exits" Help Article

**How Does NIJA Exit Positions?**

NIJA's exit system works automatically to capture profits and limit losses. Here's what happens with every position:

**Continuous Monitoring**
Your positions are checked every 2.5 minutes for exit signals. The system calculates real-time profit/loss and compares it against your exit rules.

**Four Ways Positions Exit:**

1. **Hit Profit Target** ✅
   - Position reaches your target profit level
   - Example: BTC bought at $50,000, hits $51,500 (+3%)
   - Result: Automatic sell, profit captured

2. **Hit Stop-Loss** 🛑
   - Position drops below acceptable loss level
   - Example: ETH bought at $3,000, drops to $2,976 (-0.8%)
   - Result: Automatic sell, loss limited

3. **Trailing Stop Triggered** 📈
   - Profit was higher but price pulled back
   - Example: SOL peaked at +5%, now at +2%, trailing stop at +3.5%
   - Result: Sell at +3.5%, profit protected

4. **Time Exit** ⏱️
   - Position held too long without hitting targets
   - Frees capital for new opportunities
   - Typically after several hours/days

**After Restart Protection**

If the app updates or restarts:
- All existing positions are automatically "adopted"
- Exit logic reattaches within 2.5 minutes
- Your stop-losses and profit targets remain active
- No manual action needed

**Account Independence**

Each exchange account you connect operates separately:
- Kraken account: own positions, own exits
- Coinbase account: own positions, own exits
- No cross-contamination between accounts
- All use the same proven strategy

**You're Always in Control**

- View all positions and exits in real-time
- Manually close positions anytime via exchange
- Adjust risk settings in app preferences
- Emergency liquidation available if needed

**Learning from Exits**

Every exit includes an explanation:
- "Profit target +2.5% reached - Good"
- "Stop-loss triggered at -0.8% - Protected capital"
- "Trailing stop at +3.2% - Profit secured"

This helps you learn what works and why.

---

## For Marketing Materials

### One-Sentence Version

"NIJA automatically exits positions at profit or limits losses with stop-losses, and intelligently reattaches exit logic to all positions even after app restarts."

### Short Version (50 words)

"Every position gets automatic profit targets and stop-loss protection. The system monitors positions every 2.5 minutes and exits when targets are hit. If the app restarts, it instantly adopts existing positions and reattaches exit logic. You're never left with unmanaged trades."

### Medium Version (100 words)

"NIJA protects your capital and captures profits through intelligent automated exits. Each position is continuously monitored for four exit conditions: profit targets (typically 2-5%), stop-losses (typically 0.5-1%), trailing stops that lock in gains, and time-based exits. The system scales exit targets to your account size—smaller accounts take profits faster to build capital, larger accounts can wait for bigger wins. Position adoption means that even if the app restarts, all existing positions are immediately scanned and exit logic is reattached within minutes. Each account you connect operates independently with identical protection."

### Technical Version (for reviewers)

"The exit engine operates on a 2.5-minute cycle, querying the exchange API for current positions and prices. Each position's P&L is calculated against tracked entry prices (persisted to survive restarts). Positions are checked against tiered exit conditions in priority order: (1) profit targets (exchange-fee-aware, capital-tier-scaled), (2) stop-losses (broker-specific thresholds), (3) trailing stops (dynamic based on peak profit), (4) time-based exits (capital efficiency). The adopt_existing_positions() function, called on every cycle, ensures positions present on the exchange but missing from internal tracking are immediately imported and assigned exit logic. This guarantees continuous risk management even across application restarts, crashes, or manual position opens via exchange UI. All exits are broker-API-executed market orders with comprehensive logging."

---

## Key Messaging Points

For all App Store communications, emphasize:

1. **Safety First**: Stop-losses protect capital automatically
2. **Profit Capture**: Automatic profit-taking at optimal levels
3. **Restart Resilient**: Position adoption ensures continuous management
4. **Educational**: Clear explanations of every exit decision
5. **User Control**: You can always override or manually exit
6. **Independent Accounts**: Each exchange operates separately
7. **Proven Strategy**: Same exit logic across all accounts
8. **No Surprises**: Transparent logging of all actions

## What NOT to Say

Avoid these phrases in App Store materials:

❌ "Guaranteed profits"
❌ "Never lose money"
❌ "Automated trading bot"
❌ "Set and forget"
❌ "Works while you sleep"
❌ "Get rich quick"
❌ "Beats the market"

## What TO Say Instead

✅ "Helps manage risk with automatic stop-losses"
✅ "Assists in capturing profits at target levels"
✅ "Educational trading tool with automation features"
✅ "Supports your trading decisions with intelligent exits"
✅ "Monitors positions and executes your exit strategy"
✅ "Provides continuous position management"
✅ "Transparent, logged trading decisions"

---

## Legal/Compliance Language

**Required Disclaimers:**

"Trading cryptocurrencies involves substantial risk of loss. Past performance does not guarantee future results. NIJA is an educational tool that automates trading strategies you configure. You are responsible for all trading decisions and outcomes. Always review trades before enabling automation."

**Risk Warning:**

"Automated exits help manage risk but cannot eliminate it. Stop-losses may not execute at exact prices during extreme volatility. Exchange outages may prevent exit orders from executing. You should only trade with capital you can afford to lose."

**No Investment Advice:**

"NIJA provides trading automation, not investment advice. The system executes strategies you configure based on technical indicators. We do not recommend specific trades, assets, or strategies. Consult a financial advisor for investment guidance."

---

This exit documentation is designed to be:
- ✅ Clear and understandable for non-technical users
- ✅ Accurate and honest about capabilities
- ✅ Compliant with App Store guidelines
- ✅ Educational in tone
- ✅ Transparent about risks
- ✅ Technically precise where needed
