# NIJA Security Model: How We Manage Risk

**For Investors, Partners, and Stakeholders**

> **CRITICAL SAFETY GUARANTEE**  
> **Tier-based capital protection is enforced in all environments and cannot be bypassed.**

---

## Executive Summary

NIJA is an institutional-grade automated cryptocurrency trading platform that prioritizes capital protection through a sophisticated, multi-layered risk management architecture. This document provides complete transparency into how NIJA manages risk, protects user capital, and maintains operational security.

**Our Commitment:**
- ✅ No single point of failure
- ✅ Automated circuit breakers at position, account, and platform levels
- ✅ Mandatory tier-based capital protection
- ✅ Real-time monitoring and anomaly detection
- ✅ Industry-standard encryption and security practices
- ✅ Read-only demo mode for risk-free validation

---

## Table of Contents

1. [Risk Management Philosophy](#risk-management-philosophy)
2. [Multi-Layer Risk Architecture](#multi-layer-risk-architecture)
3. [Tier-Based Capital Protection](#tier-based-capital-protection)
4. [Position and Account Level Controls](#position-and-account-level-controls)
5. [Platform-Wide Circuit Breakers](#platform-wide-circuit-breakers)
6. [Technical Security Measures](#technical-security-measures)
7. [Real-Time Monitoring and Alerts](#real-time-monitoring-and-alerts)
8. [Regulatory Compliance](#regulatory-compliance)
9. [Read-Only Demo Mode Checklist](#read-only-demo-mode-checklist)
10. [Transparency and Auditability](#transparency-and-auditability)

---

## Risk Management Philosophy

### Core Principles

**1. Capital Preservation First**
- Protecting capital is more important than chasing profits
- Risk limits are enforced, never suggested
- Conservative position sizing by default
- Multiple safety nets prevent catastrophic losses

**2. Fail-Safe Design**
- System defaults to safety when uncertain
- Errors result in trade rejection, not execution
- Manual override requires explicit authorization
- All safety controls are independently verified

**3. Layered Defense**
- No single control prevents all risk
- Multiple independent systems validate each trade
- Redundancy at position, account, and platform levels
- Circuit breakers operate independently

**4. Transparent Operation**
- All risk decisions are logged and auditable
- Users receive clear explanations for blocked trades
- Real-time visibility into risk metrics
- Complete disclosure of risk parameters

---

## Multi-Layer Risk Architecture

NIJA implements a **three-layer defense system** that validates every trade:

```
┌──────────────────────────────────────────────────────────────┐
│                   Layer 1: Core Strategy                      │
│  • Institutional-grade trading logic                          │
│  • Multi-indicator validation (RSI, ADX, MACD, VWAP, EMA)    │
│  • Trend strength requirements (ADX > 20)                     │
│  • Volume confirmation (> 50% of average)                     │
│  • Candlestick pattern validation                            │
│  ❌ PRIVATE: Cannot be accessed by users                      │
└───────────────────────────┬──────────────────────────────────┘
                            │ Signal validated ✓
                            ▼
┌──────────────────────────────────────────────────────────────┐
│              Layer 2: Risk Management & Execution             │
│  • Dynamic position sizing (2-10% based on ADX strength)     │
│  • ATR-based stop losses (volatility-adjusted)               │
│  • R-multiple profit targets (1R, 2R, 3R)                    │
│  • Tier-based capital limits (enforced per account)          │
│  • Exchange minimum checks                                    │
│  • Slippage validation                                        │
│  • Fee awareness and profitability checks                    │
│  ✅ CONTROLLED: Rate limited, capped, logged                  │
└───────────────────────────┬──────────────────────────────────┘
                            │ Risk approved ✓
                            ▼
┌──────────────────────────────────────────────────────────────┐
│                   Layer 3: User Interface                     │
│  • Read-only strategy performance view                        │
│  • Position monitoring and P&L tracking                       │
│  • Personal settings (notifications, display)                │
│  • Risk disclosures and education                            │
│  ❌ RESTRICTED: Cannot modify core strategy or risk rules     │
└──────────────────────────────────────────────────────────────┘
```

### Why Three Layers?

**Layer Isolation Prevents:**
- Users bypassing risk controls
- Unauthorized strategy modifications
- Execution of unvalidated trades
- Exposure of proprietary trading logic

**Independent Validation Ensures:**
- Each layer can reject a trade independently
- No single point of failure
- Defense-in-depth security model
- Systematic risk management

---

## Tier-Based Capital Protection

NIJA enforces **mandatory tier-based position sizing** to ensure appropriate risk management for each capital level. This system cannot be disabled or bypassed.

### Five Trading Tiers

| Tier | Capital Range | Risk/Trade | Max Positions | Trade Size | Protection Level |
|------|--------------|------------|---------------|------------|------------------|
| **SAVER** | $100–$249 | 7-10% | 2 | $15-$40 | 🛡️🛡️🛡️🛡️ Ultra-Conservative |
| **INVESTOR** | $250–$999 | 5-7% | 3 | $20-$75 | 🛡️🛡️🛡️ Conservative |
| **INCOME** | $1K–$4.9K | 3-5% | 5 | $30-$150 | 🛡️🛡️ Moderate |
| **LIVABLE** | $5K–$24.9K | 2-3% | 6 | $50-$300 | 🛡️ Balanced |
| **BALLER** | $25K+ | 1-2% | 8 | $100-$1K | ⚖️ Professional |

### Tier Enforcement Mechanisms

**1. Automatic Tier Assignment**
- System calculates tier based on current account balance
- Recalculated before every trade
- Cannot be manually overridden to higher risk tier
- Ensures protection scales with capital

**2. Position Size Limits**
- Trade size = Account Balance × Risk % × ADX Multiplier
- Larger accounts use lower risk percentages
- Prevents over-concentration in single positions
- Dynamically adjusts to market volatility (ADX-based)

**3. Maximum Position Caps**
- Hard limits on number of concurrent positions
- Prevents portfolio over-concentration
- Correlation checks prevent duplicate exposure
- System rejects new trades when at limit

**4. Trade Rejection Criteria**
```python
# Example: Tier-based validation
if trade_size > tier.max_trade_size:
    REJECT: "Trade size exceeds tier limit"
    
if open_positions >= tier.max_positions:
    REJECT: "Maximum positions reached for tier"
    
if trade_size < exchange.minimum_order_size:
    REJECT: "Trade too small for exchange requirements"
    
if estimated_fees > trade_profit_potential * 0.3:
    REJECT: "Fees would consume >30% of potential profit"
```

### Tier Graduation

Users can graduate to higher tiers through:
- **Paper Trading Success**: Demonstrate profitability risk-free
- **Increased Capital**: Deposit more funds to reach higher tier thresholds
- **Progressive Unlocking**: 14-day restricted period when transitioning to live trading

**Safety Feature**: New live traders start with $100 max position / $500 max capital for first 14 days, regardless of tier.

---

## Position and Account Level Controls

### Individual Position Protection

**Stop Loss Management**
- **Calculation**: Swing low/high + 0.5 × ATR(14)
- **Purpose**: Volatility-adjusted protection against adverse moves
- **Enforcement**: Automatically placed on every position
- **Trailing**: Activates after first profit target (TP1 at 1R)
- **Cannot be disabled**: Mandatory for all positions

**Profit Target System (R-Multiples)**
- **TP1 (1R)**: Exit 50%, move stop to breakeven
- **TP2 (2R)**: Exit additional 25% (75% total)
- **TP3 (3R)**: Exit final 25% (100% closed)
- **Trailing Stop**: ATR(14) × 1.5 from current price after TP1

**Position Circuit Breakers**
```python
# Automatic position closure triggers
if position.unrealized_loss_pct > 10%:
    FORCE_CLOSE: "10% loss limit exceeded"
    
if position.hours_open > 72 and position.pnl < 0:
    WARN: "Stale losing position (>3 days)"
    
if position.price_change_5min < -5%:
    TIGHTEN_STOP: "Rapid adverse movement detected"
```

### Account Level Protection

**Portfolio Concentration Limits**
- Maximum 80% of tier position limit prevents over-concentration
- Correlation checks block similar positions (>0.85 correlation)
- Sector/asset class diversification encouraged
- Automatic warnings at 70% of limits

**Drawdown Protection**
```python
# Account circuit breakers
if account.total_unrealized_loss_pct > 8%:
    HALT_NEW_POSITIONS: "8% account drawdown - 24hr pause"
    
if account.daily_loss_pct > 5%:
    REDUCE_SIZES: "Daily loss limit - position sizes halved"
    
if account.losing_trades_consecutive > 5:
    REVIEW_MODE: "5 consecutive losses - manual review required"
```

**Progressive Capital Limits (New Live Traders)**
- Week 1-2: Max $100/position, $500 total
- Automatic unlock after 14 days
- Graduated transition to full tier access
- Protects against early mistakes

---

## Platform-Wide Circuit Breakers

### System-Level Protection

NIJA monitors platform-wide metrics to detect and respond to systemic risks:

**1. Abnormal Loss Detection**
```python
if platform.user_loss_rate_1h > 70%:
    TRIGGER: "Platform-wide losses detected"
    ACTION: Activate global review, notify admins
    IMPACT: Increased monitoring, potential trading pause
```

**2. Exchange Connectivity Monitoring**
```python
if platform.failed_api_calls_rate > 20%:
    TRIGGER: "Exchange connectivity issues"
    ACTION: Pause new orders for all users
    IMPACT: Prevents execution during outages
```

**3. Volatility Circuit Breakers**
```python
if market.realized_volatility_1h > historical_avg × 2.5:
    TRIGGER: "Elevated market volatility"
    ACTION: Reduce position sizes by 50%, widen stops by 50%
    IMPACT: All users protected during extreme volatility
```

**4. Volume Anomaly Detection**
```python
if platform.volume_spike > 5.0:  # 5x normal
    TRIGGER: "Unusual trading volume"
    ACTION: Increase monitoring, review for manipulation
    IMPACT: Additional scrutiny on all trades
```

### Emergency Controls

**Global Emergency Exit**
- Admin-triggered platform-wide position closure
- Used only in extreme circumstances (exchange hack, major security breach)
- Closes all positions at market price
- Documented and logged with full audit trail

**Maintenance Mode**
- Blocks new position openings
- Allows position closures only
- Used during platform updates or critical issues
- Automatic notifications to all users

---

## Technical Security Measures

### API Key Security

**Encrypted Storage**
- **Encryption**: Fernet symmetric encryption (AES-128 CBC mode + HMAC SHA256)
- **Per-User Keys**: Each user's credentials stored separately
- **No Plain Text**: Keys never stored unencrypted
- **Access Control**: Decryption only when needed for trade execution

**Key Management Best Practices**
```python
# SECURE ✅
api_manager.store_user_api_key(
    user_id="user_123",
    broker="coinbase",
    api_key=encrypted_key,      # Encrypted at rest
    api_secret=encrypted_secret
)

# Retrieve and decrypt only when needed
creds = api_manager.get_user_api_key("user_123", "coinbase")
```

**Never Committed to Version Control**
- `.env` files excluded via `.gitignore`
- `.pem` certificate files excluded
- API key validation prevents accidental exposure
- Pre-commit hooks scan for secrets

### Data Protection

**User Data Isolation**
- Each user sees only their own positions and P&L
- No cross-user data access
- Database-level separation
- API permission validation on every request

**Logging and Audit Trail**
- All trades logged with user attribution
- Risk decisions recorded with reasoning
- System actions timestamped and immutable
- 90-day retention for compliance

**Rate Limiting**
- API calls throttled per user
- Prevents abuse and excessive API usage
- Exchange rate limit compliance
- Automatic backoff on limit approach

### Infrastructure Security

**Deployment Best Practices**
- Containerized deployment (Docker)
- Environment variable-based configuration
- No hardcoded credentials
- Regular security updates

**Secrets Management**
```bash
# Required environment variables
COINBASE_API_KEY=<encrypted>
COINBASE_API_SECRET=<encrypted>
COINBASE_PEM_CONTENT=<encrypted>
NIJA_ENCRYPTION_KEY=<encrypted>
```

**Pre-commit Security Checks**
- Secret scanning (gitleaks)
- Security linting (Bandit)
- Dependency vulnerability scanning
- Path traversal prevention

---

## Real-Time Monitoring and Alerts

### Live Validation Framework

**Pre-Trade Validation**
- ✅ Price data integrity (NaN, infinite, negative checks)
- ✅ Price freshness (<2 minutes old)
- ✅ Spread validation (bid-ask within 2%)
- ✅ Order size vs. minimum profitability
- ✅ Position limit enforcement
- ✅ Double-execution prevention (idempotency)

**Order Execution Validation**
- ✅ Order confirmation verification
- ✅ Timeout detection (60s limit)
- ✅ Fill price validation (within slippage tolerance)
- ✅ Slippage monitoring (max 1% allowed)

**Post-Trade Validation**
- ✅ Position reconciliation with broker
- ✅ P&L calculation validation
- ✅ Position state machine enforcement
- ✅ Fee verification against expected

### Monitoring Dashboards

**Real-Time Risk Metrics**
- Current drawdown percentage
- Open positions vs. tier limits
- Unrealized P&L
- Today's realized gains/losses
- Win rate (rolling 30 days)

**System Health Indicators**
- Exchange API latency
- Order execution success rate
- Data feed freshness
- System uptime

**Anomaly Detection**
- Unusual trading patterns
- Rapid consecutive losses
- Abnormal volatility
- Correlation spikes

### User Notifications

**Automatic Alerts**
- Position stop loss hit
- Profit target reached
- Circuit breaker triggered
- Risk limit approached
- System maintenance scheduled

**Notification Channels**
- In-app notifications
- Email alerts (optional)
- Trade confirmation receipts
- Daily summary reports

---

## Regulatory Compliance

### Financial Regulations

**Disclosure Requirements**
- ✅ Risk disclosure provided to all users before live trading
- ✅ Clear explanation of potential for loss
- ✅ No guarantee of profit statements
- ✅ Past performance disclaimers

**Geographic Restrictions**
- Compliance with local trading regulations
- Restricted territory handling
- Age verification (18+ required)
- Terms of Service acceptance

**User Protection Standards**
- Paper trading graduation system (30 days minimum)
- Progressive capital limits for new traders
- Mandatory risk education
- Read-only demo mode access

### Platform Compliance

**App Store Requirements**
- ✅ No misleading profit claims
- ✅ Clear risk disclosures
- ✅ User data privacy protection
- ✅ Financial functionality transparency
- ✅ Demo mode for risk-free testing

**Data Privacy (GDPR/CCPA)**
- User data encrypted at rest and in transit
- Right to access personal data
- Right to deletion (with trade history retention)
- No sale of user data to third parties

**Audit Trail**
- All trades logged with timestamps
- Risk decisions recorded
- User actions tracked
- 90-day minimum retention

---

## Read-Only Demo Mode Checklist

NIJA provides a **comprehensive read-only demo mode** that allows investors, partners, and prospective users to validate the platform's risk management and trading capabilities **without risking capital**.

### ✅ Demo Mode Features

#### 1. Paper Trading Account
- [ ] **Virtual Capital**: Start with $10,000 simulated funds
- [ ] **Real Market Data**: Live cryptocurrency price feeds
- [ ] **Full Strategy Execution**: Complete APEX v7.1 strategy active
- [ ] **Zero Risk**: No real money involved
- [ ] **Realistic Fees**: Simulated exchange fees and slippage
- [ ] **Performance Tracking**: Full P&L and metrics tracking

#### 2. Read-Only Strategy Visibility
- [ ] **Entry Signals**: See what triggers NIJA to enter positions
- [ ] **Exit Logic**: Understand stop loss and profit target calculations
- [ ] **Risk Calculations**: View position sizing math step-by-step
- [ ] **Indicator Values**: Access to RSI, ADX, MACD, VWAP, EMA readings
- [ ] **Market Filter Status**: See why trades are approved/blocked
- [ ] **Trend Classification**: Real-time regime detection (TRENDING/RANGING/VOLATILE)

#### 3. Risk Management Transparency
- [ ] **Tier Assignment**: See automatic tier calculation based on balance
- [ ] **Position Size Calculation**: View formula: Balance × Risk% × ADX Multiplier
- [ ] **Stop Loss Placement**: Understand swing low/high + ATR buffer
- [ ] **Profit Targets**: See 1R, 2R, 3R levels
- [ ] **Circuit Breaker Status**: View active safety limits
- [ ] **Risk Metrics Dashboard**: Drawdown, win rate, exposure

#### 4. Live Validation Testing
- [ ] **Order Validation**: See pre-trade checks in action
- [ ] **Exchange Minimum Checks**: Validate trade size requirements
- [ ] **Fee Impact Analysis**: Understand cost structure
- [ ] **Slippage Simulation**: Realistic execution modeling
- [ ] **Profitability Gates**: See minimum profit thresholds

#### 5. Educational Resources
- [ ] **Strategy Documentation**: Full APEX v7.1 guide
- [ ] **Risk Management Guide**: Complete tier system explanation
- [ ] **Trading Logic Analysis**: Deep dive into entry/exit conditions
- [ ] **Security Model**: This document (SECURITY_MODEL.md)
- [ ] **Video Tutorials**: Platform walkthrough (if available)

#### 6. Performance Analytics
- [ ] **Trade History**: View all simulated trades
- [ ] **Win/Loss Ratio**: Calculate success rate
- [ ] **R-Multiple Returns**: Average risk-to-reward
- [ ] **Drawdown Tracking**: Maximum peak-to-trough decline
- [ ] **Sharpe Ratio**: Risk-adjusted return metric
- [ ] **Monthly Performance**: Historical breakdown

### 🚀 Activating Demo Mode

**For Investors and Partners:**
```bash
# Set environment variable
export TRADING_MODE=PAPER

# Run simulation
python simulate_live_trade.py --detailed

# Start paper trading bot
python bot.py --paper-mode
```

**Via Web/Mobile Interface:**
1. Create account
2. Select "Paper Trading Mode" (default for new users)
3. Explore platform risk-free for 30+ days
4. Graduate to live trading after meeting criteria

### 📊 Demo Mode Graduation Criteria

Before transitioning to live trading, users must demonstrate:
- ✅ **30 days** minimum in paper trading
- ✅ **20+ trades** completed
- ✅ **40%+ win rate**
- ✅ **<30% maximum drawdown**
- ✅ **60/100+ risk management score**

**Progressive Unlocking**: Even after graduation, new live traders have $100 max position / $500 max capital limits for first 14 days.

### 🔍 Investor Due Diligence Checklist

For investors evaluating NIJA, verify these demo mode capabilities:

**Technical Validation**
- [ ] Run backtests on historical data (5+ years available)
- [ ] Observe live paper trading for 7+ days
- [ ] Review trade execution logs
- [ ] Validate stop loss placement accuracy
- [ ] Confirm profit target achievement

**Risk Management Validation**
- [ ] Test tier-based position sizing
- [ ] Trigger circuit breakers intentionally
- [ ] Verify maximum drawdown protection
- [ ] Validate correlation detection
- [ ] Test emergency exit functionality

**Security Validation**
- [ ] Review API key encryption implementation
- [ ] Audit user data isolation
- [ ] Test rate limiting
- [ ] Verify logging and audit trails
- [ ] Check for security vulnerabilities (CodeQL available)

**Regulatory Validation**
- [ ] Review risk disclosure language
- [ ] Verify paper trading graduation system
- [ ] Check geographic restriction handling
- [ ] Validate Terms of Service
- [ ] Confirm audit trail retention

---

## Transparency and Auditability

### Open Architecture

**Code Transparency**
- Core risk management logic documented
- Strategy logic principles disclosed (implementation proprietary)
- Security measures publicly documented
- Regular security audits

**Performance Transparency**
- Real-time P&L tracking
- Historical performance data
- Win rate and R-multiple statistics
- Drawdown tracking and reporting

### Third-Party Validation

**Security Scanning**
- CodeQL static analysis
- Dependency vulnerability scanning (Bandit)
- Secret scanning (gitleaks)
- Pre-commit security hooks

**Exchange Verification**
- Position reconciliation with broker
- Fee validation against exchange data
- Balance verification via API
- Trade confirmation matching

### Audit Trail

**Immutable Records**
- All trades logged with timestamps
- Risk decisions recorded with reasoning
- Circuit breaker activations documented
- User actions tracked

**Data Retention**
- 90-day minimum log retention
- Trade history permanently stored
- P&L calculations archived
- Compliance reporting available

### Investor Reporting

**Monthly Reports** (Available on Request)
- Platform-wide performance summary
- Risk metrics aggregate
- User growth and retention
- System uptime and reliability
- Security incident log (if any)

**Real-Time Dashboard** (For Stakeholders)
- Current open positions across platform
- Aggregate P&L
- Circuit breaker status
- Exchange connectivity health
- User tier distribution

---

## Risk Acknowledgment

### Investor Disclosure

**Material Risks**

1. **Market Risk**: Cryptocurrency prices are highly volatile. Losses can occur rapidly.

2. **Technology Risk**: Software, connectivity, or exchange issues may impact trading.

3. **Execution Risk**: Slippage, latency, or partial fills may affect profitability.

4. **Regulatory Risk**: Cryptocurrency regulations are evolving and may restrict operations.

5. **Operational Risk**: Despite safeguards, no automated system eliminates all risk.

**No Guarantee of Profit**
- Past performance does not predict future results
- Backtests may not reflect live trading conditions
- Market conditions change and strategies may underperform
- Users may lose some or all of their invested capital

**User Responsibility**
- Users must understand and accept all risks
- Only invest capital you can afford to lose
- Monitor positions regularly
- Comply with local regulations and tax obligations

---

## Conclusion

NIJA's security model represents **institutional-grade risk management** designed for retail traders. Through multi-layer defense, tier-based capital protection, automated circuit breakers, and complete transparency, NIJA prioritizes capital preservation while enabling systematic cryptocurrency trading.

### Key Takeaways

✅ **No Single Point of Failure**: Multiple independent systems validate every trade

✅ **Mandatory Protection**: Risk controls cannot be disabled or bypassed

✅ **Transparent Operation**: Complete visibility into risk decisions and system status

✅ **Progressive Safety**: New traders protected with paper trading and capital limits

✅ **Real-Time Monitoring**: Continuous risk assessment and automatic intervention

✅ **Regulatory Compliance**: Built for app store approval and financial regulations

✅ **Auditable Records**: Complete trade history and decision logging

### For Investors

NIJA provides the **transparency, security, and risk management** that institutional investors expect, packaged for retail accessibility. The read-only demo mode allows complete validation of the platform's capabilities before any capital commitment.

**Next Steps:**
1. Review this security model in detail
2. Activate demo mode and observe live paper trading
3. Review strategy documentation (APEX_V71_DOCUMENTATION.md)
4. Test risk management features firsthand
5. Evaluate performance metrics over 30+ days
6. Schedule investor Q&A session

---

## Additional Resources

- **Strategy Guide**: [APEX_V71_DOCUMENTATION.md](APEX_V71_DOCUMENTATION.md)
- **Risk Profiles**: [RISK_PROFILES_GUIDE.md](RISK_PROFILES_GUIDE.md)
- **Security Details**: [SECURITY.md](SECURITY.md)
- **Institutional Guardrails**: [INSTITUTIONAL_GUARDRAILS.md](INSTITUTIONAL_GUARDRAILS.md)
- **Paper Trading Guide**: [PAPER_TRADING_GRADUATION_GUIDE.md](PAPER_TRADING_GRADUATION_GUIDE.md)
- **Simulation Quick Start**: [SIMULATION_QUICK_START.md](SIMULATION_QUICK_START.md)
- **Risk Disclosure**: [RISK_DISCLOSURE.md](RISK_DISCLOSURE.md)
- **Terms of Service**: [TERMS_OF_SERVICE.md](TERMS_OF_SERVICE.md)

---

**Document Version**: 1.0  
**Last Updated**: February 4, 2026  
**Maintained By**: NIJA Development Team  
**Contact**: For investor inquiries, please reach out through official channels

---

*This document is part of NIJA's commitment to transparency and investor protection. All statements are accurate as of the publication date. Risk management systems are continuously improved, and this document will be updated to reflect material changes.*
