# 🔒 RISK FREEZE POLICY - NIJA Trading Bot

**Effective Date:** February 12, 2026  
**Status:** 🔒 **ACTIVE - PERMANENT**

---

## 🎯 PURPOSE

This RISK FREEZE establishes permanent governance over all risk management rules to ensure the trading bot remains profitable and safe long-term.

### Core Principle

> **"No live changes to risk rules without validation through backtesting, simulation, versioning, and explicit approval."**

This is how real trading systems stay profitable long-term. Ad-hoc risk parameter changes are the #1 cause of strategy degradation in automated trading.

---

## 🚫 WHAT IS FROZEN

### ❌ No Changes Allowed Without Approval

From this point forward, the following require the full approval process:

#### 1. Risk Parameter Changes
- Position sizing rules (min/max position size)
- Stop-loss calculations and distances
- Take-profit levels and percentages
- Daily loss limits
- Maximum drawdown limits
- Exposure limits
- Leverage limits
- Margin requirements
- Risk per trade percentages

#### 2. Risk Management Logic
- Position sizing algorithms
- Stop-loss calculation methods
- Trailing stop mechanisms
- Take-profit tier calculations
- Risk validation logic
- Circuit breaker thresholds
- Position limits

#### 3. Protected Files
Any changes to these files require full approval:
- `bot/risk_manager.py`
- `bot/apex_risk_manager.py`
- `bot/risk_management.py`
- `bot/user_risk_manager.py`
- `bot/validators/risk_validator.py`
- `bot/apex_config.py` (RISK_LIMITS, POSITION_SIZING, STOP_LOSS sections)
- `bot/tier_config.py` (risk-related parameters)
- Any other file containing risk parameter constants

---

## ✅ APPROVAL PROCESS

All risk parameter changes MUST follow this process:

### Step 1: Proposal & Documentation
**Required:**
- **Risk Change Proposal Document** including:
  - Current parameter values
  - Proposed parameter values
  - Rationale for change
  - Expected impact on profitability
  - Expected impact on risk exposure
  - Test plan

### Step 2: Backtesting
**Required:**
- Minimum 3 months historical data
- Test on multiple market conditions (trending, ranging, volatile)
- Compare metrics:
  - Win rate
  - Average R-multiple
  - Maximum drawdown
  - Sharpe ratio
  - Sortino ratio
  - Total return
- Document all results with visualizations

**Acceptance Criteria:**
- ✅ Win rate maintained or improved
- ✅ Maximum drawdown not increased by >10%
- ✅ Sharpe ratio maintained or improved
- ✅ No catastrophic failure scenarios introduced

### Step 3: Paper Trading Simulation
**Required:**
- Minimum 2 weeks paper trading with proposed changes
- Real-time market conditions
- Full position lifecycle tracking
- Daily monitoring and reporting

**Acceptance Criteria:**
- ✅ No unexpected behavior
- ✅ Risk metrics within acceptable ranges
- ✅ Strategy performs as backtested
- ✅ No edge cases causing failures

### Step 4: Versioning
**Required:**
- Create new risk configuration version
- Version format: `RISK_CONFIG_v{MAJOR}.{MINOR}.{PATCH}`
- Document in version changelog:
  - What changed
  - Why it changed
  - Test results summary
  - Approval signatures
- Maintain backward compatibility (old configs still loadable)

### Step 5: Code Review & Approval
**Required Approvals:**
- ✅ Technical Lead - validates implementation
- ✅ Risk Manager (if different from Technical Lead) - validates risk impact
- ✅ Strategy Developer - validates strategy consistency

**Review Checklist:**
- Code follows risk freeze policy
- All tests pass (unit, integration, backtest)
- Documentation complete
- Version properly incremented
- Change log updated
- No unintended side effects

### Step 6: Gradual Rollout
**Required:**
- Deploy to paper trading first (minimum 3 days)
- If successful, deploy to 10% of live capital (minimum 1 week)
- If successful, deploy to 50% of live capital (minimum 1 week)  
- If successful, deploy to 100% of live capital
- Monitor metrics at each stage
- **Rollback immediately** if metrics degrade

---

## 🚨 EMERGENCY EXCEPTIONS

### When Immediate Changes Are Allowed

**ONLY in these scenarios:**

1. **Critical Safety Issue**
   - Active trading causing immediate capital loss
   - Risk limit breach causing liquidation risk
   - Stop-loss failures causing runaway losses
   - **Action:** Halt trading first, then fix

2. **Regulatory Compliance**
   - New regulation requires immediate change
   - Legal requirement for risk limit modification
   - **Action:** Document legal requirement, implement minimal change

3. **Exchange Rule Changes**
   - Exchange modifies margin requirements
   - Exchange changes position limits
   - Exchange updates trading rules
   - **Action:** Adapt to maintain operation, document change

### Emergency Exception Process

1. **Declare Emergency**
   - Document the emergency situation
   - Explain why it can't wait for full approval
   - Estimate impact of NOT making the change

2. **Make Minimal Change**
   - Change ONLY what is necessary
   - Document exactly what was changed
   - Create rollback plan

3. **Immediate Notification**
   - Alert all stakeholders
   - Log change in emergency change log
   - Schedule post-mortem review

4. **Post-Emergency Follow-up** (within 48 hours)
   - Full retroactive approval process
   - Backtest the emergency change
   - Paper trade the change
   - Either: Formalize as permanent OR rollback to previous config
   - Document lessons learned

---

## 📊 RISK CONFIGURATION VERSIONING

### Version Format

```
RISK_CONFIG_v{MAJOR}.{MINOR}.{PATCH}

MAJOR: Breaking changes to risk model
MINOR: New risk rules or significant adjustments  
PATCH: Minor parameter tuning
```

### Version History Template

```yaml
version: RISK_CONFIG_v2.1.0
date: 2026-02-12
author: Technical Lead
status: approved

changes:
  - parameter: max_position_size
    old_value: 0.10
    new_value: 0.08
    reason: Reduce exposure during high volatility period
    
  - parameter: stop_loss_atr_multiplier
    old_value: 1.5
    new_value: 1.8
    reason: Reduce premature stop-outs

backtesting:
  period: 2025-11-12 to 2026-02-12
  results:
    win_rate: 0.58 (+0.03)
    max_drawdown: 0.12 (-0.01)
    sharpe_ratio: 1.85 (+0.15)
  conclusion: Approved - improvements across all metrics

paper_trading:
  period: 2026-01-29 to 2026-02-12
  trades: 47
  win_rate: 0.60
  max_drawdown: 0.08
  conclusion: Approved - consistent with backtest

approvals:
  - role: Technical Lead
    name: [Name]
    date: 2026-02-12
    signature: [Signature]
    
  - role: Risk Manager
    name: [Name]
    date: 2026-02-12
    signature: [Signature]
```

### Current Version

**RISK_CONFIG_v1.0.0** - Baseline configuration (as of February 12, 2026)

---

## 🔍 MONITORING & COMPLIANCE

### Automated Enforcement

**Pre-commit Hooks:**
- Detect changes to risk configuration files
- Block commit if no version number incremented
- Require approval signatures in commit message

**CI/CD Checks:**
- Verify risk configuration version is incremented
- Verify backtest results are attached
- Verify approval signatures present
- Block merge if any check fails

**Runtime Monitoring:**
- Log current risk configuration version on startup
- Alert if risk parameters change unexpectedly
- Track risk limit breaches
- Report daily risk metrics

### Manual Reviews

**Weekly Risk Review:**
- Review all risk parameter changes (even if approved)
- Analyze impact on strategy performance
- Check for unintended consequences
- Validate risk limits are being respected

**Monthly Risk Audit:**
- Full review of risk configuration history
- Compliance check against policy
- Performance analysis vs. risk changes
- Identify improvement opportunities

**Quarterly Strategy Review:**
- Deep analysis of risk/reward profile
- Backtest current configuration vs. alternatives
- Consider strategic risk adjustments
- Plan next quarter's risk configuration roadmap

---

## 📋 CHANGE TRACKING

### Risk Change Log

All risk changes must be logged here:

#### RISK_CONFIG_v1.0.0 (Baseline)
**Date:** February 12, 2026  
**Status:** Active  
**Changes:** Initial frozen configuration

**Parameters:**
- Position sizing: 1-10% per trade based on trend quality
- Stop-loss: ATR-based, 1.5x multiplier
- Take-profit: Tiered (TP1: 0.8%, TP2: 1.5%, TP3: 2.5%)
- Max daily loss: 2.5%
- Max drawdown: 10%
- Max exposure: 30%
- Max positions: 10
- Max leverage: 3x

**Approvals:**
- Technical Lead: Approved (Risk Freeze Declaration)

---

## 🎓 PHILOSOPHY & RATIONALE

### Why Risk Freeze Matters

**1. Strategy Degradation Prevention**
- Ad-hoc parameter tweaks are #1 cause of strategy failure
- "Just one more adjustment" syndrome destroys profitable systems
- Discipline in risk management = long-term profitability

**2. Institutional-Grade Governance**
- Professional trading firms require formal approval for risk changes
- Regulatory compliance demands documented risk management
- Audit trail protects against accusations of reckless trading

**3. Psychological Protection**
- Prevents emotional reactions to short-term losses
- Enforces systematic thinking over reactive changes
- Builds confidence in the strategy through rigorous validation

**4. Capital Protection**
- User capital is at stake
- Conservative, well-tested risk rules protect traders
- One bad risk change can wipe out months of gains

### What We Learn From This

The RISK FREEZE teaches:
- **Patience:** Good risk management requires testing and validation
- **Discipline:** Following the process even when you want to "just tweak it"
- **Rigor:** Documenting and measuring everything
- **Humility:** Admitting we don't know the perfect parameters without testing
- **Professionalism:** Operating like a real trading firm

---

## 📞 CONTACTS

### Risk Freeze Enforcement
- **Risk Manager:** risk@nija.trading
- **Technical Lead:** dev@nija.trading
- **Escalation:** compliance@nija.trading

### Change Proposals
- **Submit to:** risk-changes@nija.trading
- **CC:** Technical Lead, Strategy Team

### Questions
- **General:** team@nija.trading
- **Policy Clarification:** risk@nija.trading

---

## 📚 REFERENCES

### Related Policies
- `FEATURE_FREEZE_POLICY.md` - General feature freeze during App Store review
- `POSITION_MANAGEMENT_POLICY.md` - Position management rules
- `DEPLOYMENT_CHECKLIST.md` - Deployment procedures

### Risk Management Files
- `bot/risk_manager.py` - Main risk management engine
- `bot/apex_risk_manager.py` - APEX strategy risk manager
- `bot/risk_management.py` - Risk management module
- `bot/validators/risk_validator.py` - Risk validation logic
- `bot/apex_config.py` - Risk configuration parameters

### Testing & Validation
- `bot/*backtest*.py` - Backtesting scripts
- `bot/test_apex_integration.py` - Integration tests
- Paper trading infrastructure

---

## ✅ POLICY ACKNOWLEDGMENT

By working on NIJA risk management, all team members acknowledge:

1. ✅ I have read and understand this RISK FREEZE policy
2. ✅ I will NOT change risk parameters without full approval
3. ✅ I will follow the 6-step approval process for any risk changes
4. ✅ I understand that ad-hoc risk changes destroy profitability
5. ✅ I commit to institutional-grade risk governance

---

## 📝 VERSION HISTORY

**v1.0** - February 12, 2026
- Initial RISK FREEZE policy created
- Establishes permanent governance framework
- Effective immediately and ongoing

**Policy Updates:**
- Changes to this policy require: Risk Manager + Technical Lead + Compliance Officer approval

---

**This RISK FREEZE is PERMANENT and applies to all future development.**

**Status: 🔒 ACTIVE - PERMANENT**

---

## 🔐 COMMITMENT

**We solemnly commit that:**

> From this point forward, NO risk management changes will be deployed to production without:
> 1. ✅ Backtesting (minimum 3 months)
> 2. ✅ Paper Trading (minimum 2 weeks)
> 3. ✅ Version documentation
> 4. ✅ Multi-stakeholder approval
> 
> **This is how real trading systems stay profitable long-term.**

---

_"Discipline is choosing between what you want now and what you want most."_  
_— NIJA Trading Systems_
