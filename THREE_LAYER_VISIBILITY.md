# NIJA Three-Layer Visibility System

## Overview

NIJA provides **three complementary visibility layers** to give you complete transparency into your trading activity. Each layer serves a distinct purpose and shows you different aspects of the trading system.

### Why Three Layers?

**The Problem**: Traditional trading systems only show you what executes on the exchange. You never know:
- What signals the bot considered
- Why certain trades were rejected
- What filters blocked potential opportunities
- Whether positions are still open if the broker UI lags

**The Solution**: NIJA's three-layer system gives you complete visibility from signal generation to execution proof.

---

## The Three Visibility Layers

### 1️⃣ Kraken Trade History (Execution Proof)

**What It Shows**: Official record from the exchange
**Trust Level**: 🏦 Exchange-verified (100% accurate)
**Update Speed**: ⚡ 1-2 seconds
**Purpose**: Legal proof of what actually executed

**Where to Access**:
- Kraken.com → Portfolio → Trade History
- Mobile App → Portfolio → Trades
- See [KRAKEN_TRADING_GUIDE.md](KRAKEN_TRADING_GUIDE.md) for detailed instructions

**What You'll Find**:
- ✅ All filled orders (buys, sells)
- ✅ Exact execution prices
- ✅ Actual fees paid
- ✅ Timestamps
- ✅ Order IDs for auditing

**Limitations**:
- ❌ Doesn't show rejected signals
- ❌ No explanation of why trades happened
- ❌ No visibility into NIJA's decision-making
- ❌ May lag during high volatility

**Use Cases**:
- Tax reporting and accounting
- Verifying NIJA executed correctly
- Checking actual vs. expected prices
- Fee analysis and optimization

---

### 2️⃣ NIJA Activity Feed (Decision Truth)

**What It Shows**: Every decision NIJA makes
**Trust Level**: 🤖 Bot reporting (NIJA's internal view)
**Update Speed**: ⚡ Real-time (instant)
**Purpose**: Understand WHY trades did or didn't happen

**Where to Access**:
- NIJA Dashboard → Activity Feed section
- API endpoint: `GET /api/activity/recent`

**What You'll Find**:
- ✅ All signals generated (long, short, neutral)
- ✅ Signals accepted vs. rejected
- ✅ **Rejection reasons** (fees, size, risk limits)
- ✅ Filter blocks (pair quality, volatility, spread)
- ✅ Fee impact analysis
- ✅ Stablecoin routing decisions
- ✅ Risk limit triggers
- ✅ Position exits (stop-loss, take-profit, signals)

**Example Activity Events**:

```
✅ EXECUTED: BUY 0.05 ETH/USD @ $3,250.00 on kraken
❌ Signal REJECTED: LONG BTC/USDT - Pair quality check failed (spread > 0.15%)
🚫 FILTER BLOCK: SOL/USD - Minimum size $15.00 not met (attempted $12.50)
💸 FEE BLOCK: XRP/USD - Estimated fees $0.85 (6.8% of $12.50 position)
🔀 STABLECOIN ROUTED: ETH/USDT - coinbase → kraken (lower fees)
⚠️ RISK LIMIT HIT: daily_loss - -2.5% / -3.0% max
📈 POSITION CLOSED: ETH/USD - Take Profit 1 hit (P&L: +$23.50)
```

**Use Cases**:
- Understanding why no trade happened
- Diagnosing issues (too many rejections?)
- Learning NIJA's behavior
- Identifying pattern in filters
- Seeing fee impact before trades execute

**Key Insight**:
> This is **Decision Truth** - it shows what NIJA _considered_, not just what executed. Use this to understand the "why" behind every action.

---

### 3️⃣ Live Position Mirror (Real-Time Positions)

**What It Shows**: Current open positions
**Trust Level**: 🤖 NIJA tracking (updated immediately)
**Update Speed**: ⚡ Instant (doesn't wait for broker)
**Purpose**: Know what's open even when broker UI lags

**Where to Access**:
- NIJA Dashboard → Live Position Mirror section
- API endpoint: `GET /api/positions/live`

**What You'll Find**:
- 🔄 All currently open positions
- 🔄 Entry price and current price
- 🔄 Unrealized P&L (live updates)
- 🔄 Stop-loss and take-profit levels
- 🔄 Hold time in minutes
- 🔄 Position health status
- 🔄 Which broker holds the position

**Example Position Display**:

| Symbol | Broker | Side | Entry | Current | Size | P&L | Hold Time |
|--------|--------|------|-------|---------|------|-----|-----------|
| ETH/USD | kraken | LONG | $3,250 | $3,275 | $50.00 | +$0.38 (+0.77%) | 12m |
| BTC/USDT | coinbase | LONG | $68,500 | $68,350 | $75.00 | -$0.16 (-0.22%) | 45m |

**Why It's Needed**:
- Kraken UI can lag during high volatility
- WebSocket disconnections cause delays
- API rate limiting slows broker responses
- You need to know positions **right now**

**Use Cases**:
- Monitoring positions during fast markets
- Knowing what to expect in Kraken before it updates
- Emergency position checks
- Quick P&L assessment

**Key Insight**:
> This is NIJA's **internal view** of positions. It updates the instant a trade executes, before the broker confirms. Use this when you need immediate position awareness.

---

## How to Use All Three Layers Together

### 🎯 Recommended Workflow

#### For Trade Verification
1. **Check Activity Feed**: Did NIJA decide to trade?
2. **Check Kraken**: Did the trade actually execute?
3. **Compare prices**: Did execution match expected price?

#### For Understanding Rejections
1. **Activity Feed**: Find the rejection event
2. **Read rejection reason**: Fees? Size? Risk limit?
3. **Adjust strategy**: Maybe lower tier minimum or add capital

#### For Position Monitoring
1. **Live Position Mirror**: Quick P&L check
2. **Kraken positions**: Verify broker agrees
3. **Activity Feed**: Review entry decision quality

#### For Performance Analysis
1. **Kraken History**: Get exact P&L for tax purposes
2. **Activity Feed**: Understand win rate context (rejections matter!)
3. **Position Mirror**: Track open position performance

---

## Visibility Layer Comparison

| Feature | Kraken | Activity Feed | Position Mirror |
|---------|--------|---------------|-----------------|
| **Shows Executed Trades** | ✅ Yes | ✅ Yes | ✅ Yes (open only) |
| **Shows Rejected Signals** | ❌ No | ✅ Yes | ❌ No |
| **Shows Filter Reasons** | ❌ No | ✅ Yes | ❌ No |
| **Shows Fee Analysis** | ✅ Actual fees | ✅ Estimated fees | ✅ Paid fees |
| **Shows Why No Trade** | ❌ No | ✅ Yes | ❌ No |
| **Real-Time Updates** | ⚡ Fast (1-2s) | ⚡ Instant | ⚡ Instant |
| **Survives Broker Lag** | ❌ No (IS the lag) | ✅ Yes | ✅ Yes |
| **Legal/Tax Valid** | ✅ Yes | ❌ No | ❌ No |
| **Auditable** | ✅ Exchange record | ⚠️ Bot logs | ⚠️ Bot tracking |
| **Trust Level** | 🏦 Official | 🤖 Internal | 🤖 Internal |

---

## Common Questions

### Q: Which layer should I check first?

**A**: Depends on your goal:
- **Trading decision analysis** → Activity Feed
- **Tax/accounting** → Kraken Trade History
- **Quick P&L check** → Live Position Mirror

### Q: What if Activity Feed shows trade but Kraken doesn't?

**A**: Possible causes:
1. **Broker lag** - Wait 5-10 seconds for Kraken to update
2. **Trade failed** - Check Activity Feed for error event
3. **API issue** - Check NIJA logs for broker errors

If it persists >1 minute, NIJA likely logged the intent but execution failed.

### Q: Can I trust the Activity Feed over Kraken?

**A**: For legal/tax purposes, **always trust Kraken** (it's the exchange's official record).

For understanding NIJA's behavior and decisions, **trust the Activity Feed** (it shows intent).

Use both together: Activity Feed explains _why_, Kraken proves _what actually happened_.

### Q: Why is Position Mirror P&L different from Kraken?

**A**: Position Mirror calculates P&L instantly using:
- Last known market price (may be delayed by seconds)
- NIJA's entry price tracking

Kraken shows P&L based on:
- Real-time order book prices
- Their official position tracking

Differences should be < 0.5% and resolve within seconds.

### Q: How do I know if a signal was rejected for fees?

**A**: Check the Activity Feed for events like:
```
💸 FEE BLOCK: XRP/USD - Estimated fees $0.85 (6.8% of $12.50 position)
```

This tells you NIJA blocked the trade because fees would eat too much profit.

### Q: What does "stablecoin routed to Kraken" mean?

**A**: NIJA automatically routes USDT/USDC trades to Kraken for lower fees:
```
🔀 STABLECOIN ROUTED: ETH/USDT - coinbase → kraken (lower fees)
```

This saves ~0.18% per trade (Kraken fees: 0.26% vs Coinbase: 0.60%).

---

## Tier-Based Visibility

NIJA shows trades differently based on your trading tier:

| Tier | Min Visible Size | Why? |
|------|-----------------|------|
| **STARTER** | $10 | Show all trades for entry level |
| **SAVER** | $15 | Show all trades for learning |
| **INVESTOR** | $20 | Filter out micro-adjustments |
| **INCOME** | $30 | Focus on meaningful trades |
| **LIVABLE** | $50 | Professional-level filtering |
| **BALLER** | $100 | High-signal, low-noise |

Trades below your tier's minimum are **still executed** but shown as:
```
📏 MIN SIZE BLOCK: SOL/USD - $18.50 < $30.00 (tier: INCOME)
```

This reduces noise in the Activity Feed while preserving full execution history.

---

## Technical Details

### Activity Feed Storage
- Format: JSONL (one JSON event per line)
- Location: `./data/activity_feed/activity_feed.jsonl`
- Retention: 30 days (auto-archived)
- Max in-memory: 1,000 recent events

### Position Mirror Storage
- Format: JSON
- Location: `./data/positions/live_positions.json`
- Updates: Every price tick + every trade
- Persistence: Survives bot restarts

### API Endpoints
```
GET /api/activity/recent?limit=100&type=signal_rejected
GET /api/activity/summary?hours=24
GET /api/activity/rejections?hours=24
GET /api/positions/live
GET /api/positions/summary
GET /api/positions/broker/{broker_name}
```

---

## Configuration

### Stablecoin Policy

Control how NIJA handles stablecoin pairs (USDT, USDC, DAI) via `.env`:

```bash
# Route all stablecoin trades to Kraken (recommended - lower fees)
STABLECOIN_POLICY=route_to_kraken

# Block all stablecoin trades
STABLECOIN_POLICY=block_all

# Allow stablecoin trades on any broker
STABLECOIN_POLICY=allow_all
```

**Recommendation**: Use `route_to_kraken` to save ~0.34% round-trip fees.

---

## Next Steps

1. ✅ **Read the Kraken Guide**: [KRAKEN_TRADING_GUIDE.md](KRAKEN_TRADING_GUIDE.md)
2. ✅ **Configure stablecoin policy** in `.env`
3. ✅ **Open NIJA Dashboard** to see Activity Feed and Position Mirror
4. ✅ **Make a test trade** and watch all three layers update
5. ✅ **Compare layers** to understand each one's purpose

---

## Support

- **Activity Feed not updating?** Check bot logs for errors
- **Position Mirror empty?** No open positions or bot just started
- **Kraken doesn't match?** Wait 10 seconds for exchange to update

For detailed Kraken verification steps, see [KRAKEN_TRADING_GUIDE.md](KRAKEN_TRADING_GUIDE.md).

---

**Last Updated**: January 2026
**Version**: 1.0
**Author**: NIJA Trading Systems
