# APP STORE MODE - README Additions

Add these sections to the main README.md file:

---

## 🍎 App Store Mode

NIJA includes a special **APP_STORE_MODE** flag for safe Apple App Store review. When enabled, all live trading is blocked while maintaining full UI functionality for reviewers.

### Quick Start

**For App Store Review:**
```bash
# In .env file
APP_STORE_MODE=true
```

**For Normal Operation:**
```bash
# In .env file
APP_STORE_MODE=false
```

### What It Does

When `APP_STORE_MODE=true`:

✅ **Available for Reviewers:**
- Full dashboard interface
- Account balance display (read-only)
- Trading history viewing
- Performance metrics
- Risk disclosures
- Simulation mode

❌ **Blocked for Safety:**
- Live trading execution
- Real money transactions
- Exchange API order placement
- Any financial risk

### Implementation

APP_STORE_MODE provides **multi-layer protection**:

1. **Layer 0**: Broker `place_market_order()` - Hard block at execution layer
2. **Layer 1**: Hard controls `can_trade()` - Safety controller check  
3. **Layer 2**: LIVE_CAPITAL_VERIFIED - Master safety switch
4. **Layer 3**: Kill switches - Emergency stop

No live trades can execute when APP_STORE_MODE is enabled. The blocking cannot be bypassed.

### Verification

Run the verification test suite:

```bash
python qa_app_store_mode.py --full
```

Expected output:
```
Total Tests: 22
Passed: 22
Failed: 0
Success Rate: 100.0%
✅ ALL QA TESTS PASSED
```

### Documentation

- **Implementation Guide**: [APP_STORE_MODE_IMPLEMENTATION.md](APP_STORE_MODE_IMPLEMENTATION.md)
- **Submission Guide**: [APP_STORE_SUBMISSION_GUIDE.md](APP_STORE_SUBMISSION_GUIDE.md)
- **Review Checklist**: [APP_STORE_REVIEW_CHECKLIST.md](APP_STORE_REVIEW_CHECKLIST.md)
- **Python Snippet**: [APP_STORE_MODE_SNIPPET.py](APP_STORE_MODE_SNIPPET.py)

### Apple Reviewers

If you're an Apple reviewer testing this app:

1. **Mode Status**: APP_STORE_MODE is currently **ENABLED**
2. **Safety**: No real trades will execute - completely safe to test
3. **Features**: All UI and read-only features are fully functional
4. **Disclosures**: All risk warnings are visible throughout the app
5. **Documentation**: See reviewer notes in App Store Connect submission

For questions: See reviewer notes or contact support listed in App Store Connect.

---

## Safety & Compliance

### Risk Disclosures

**IMPORTANT**: Trading involves substantial risk of loss. Key points:

- **Independent Trading**: Each account trades independently using the same algorithm. NO trade copying occurs.
- **Financial Risk**: You may lose all invested capital. Only invest what you can afford to lose.
- **Not Financial Advice**: NIJA is software, not a financial advisor.
- **User Responsibility**: You maintain full control and are responsible for all trades.
- **Age Requirement**: 18+ years old (21+ in some jurisdictions).

### Safety Controls

NIJA includes multiple safety layers:

1. **APP_STORE_MODE**: Blocks live execution during App Store review
2. **LIVE_CAPITAL_VERIFIED**: Master switch for live trading
3. **Hard Controls**: Position limits (2-10%), daily loss limits
4. **Kill Switches**: Global and per-user emergency stops
5. **DRY_RUN_MODE**: Test mode for strategy validation

### Compliance

- **Apple Guidelines**: Meets 2.3.8 (functional), 5.1.1 (disclosures)
- **Financial App Safety**: Zero financial risk during review
- **User Control**: Users maintain full control of exchange accounts
- **No In-App Purchases**: Users connect their own exchange APIs

---

## Configuration

### Environment Variables

Key configuration flags:

```bash
# APP STORE MODE (for Apple review)
APP_STORE_MODE=false              # Set to 'true' for App Store submission

# LIVE TRADING CONTROL
LIVE_CAPITAL_VERIFIED=false       # Master switch for live trading
DRY_RUN_MODE=false                # Simulation mode

# HEARTBEAT TRADE (verification)
HEARTBEAT_TRADE=false             # Enable test trade verification
HEARTBEAT_TRADE_SIZE=5.50         # Test trade size in USD
```

For complete configuration options, see [.env.example](.env.example).

---

## Testing

### Test Suites

Run comprehensive tests:

```bash
# Basic functionality tests
python test_app_store_mode.py

# Enhanced QA verification
python qa_app_store_mode.py --full

# Security checks (if available)
python -m pytest tests/
```

### Expected Results

All test suites should pass:

- **test_app_store_mode.py**: 5/5 tests
- **qa_app_store_mode.py**: 22/22 tests
- Zero failures required for App Store submission

---

## For Developers

### Working with APP_STORE_MODE

When adding new trading features:

1. **Check Mode**: Always check `is_app_store_mode_enabled()` before execution
2. **Block Execution**: Use `check_execution_allowed()` to validate
3. **Simulate Response**: Return simulated data when blocked
4. **Log Attempts**: Log all blocking attempts for audit

Example:

```python
from bot.app_store_mode import get_app_store_mode

def place_order(symbol, side, quantity):
    # Check APP_STORE_MODE
    app_store_mode = get_app_store_mode()
    if app_store_mode.is_enabled():
        return app_store_mode.block_execution_with_log(
            operation='place_order',
            symbol=symbol,
            side=side,
            size=quantity
        )
    
    # Normal execution (only reached if mode disabled)
    return broker.place_order(symbol, side, quantity)
```

### Adding New Endpoints

For new API endpoints:

1. Add read-only version in `bot/app_store_reviewer_api.py`
2. Test with `APP_STORE_MODE=true`
3. Verify no live execution possible
4. Update QA script if needed

---

## License & Legal

### Terms of Service

By using NIJA, you agree to:
- Trading involves risk of loss
- You are responsible for all trades
- You maintain control of your exchange accounts
- You comply with all applicable laws

See [TERMS_OF_SERVICE.md](TERMS_OF_SERVICE.md) for complete terms.

### Privacy Policy

See [PRIVACY_POLICY.md](PRIVACY_POLICY.md) for our privacy practices.

### Risk Disclosure

See [RISK_DISCLOSURE.md](RISK_DISCLOSURE.md) for complete risk information.

---

## Support

### Documentation

- [Getting Started](GETTING_STARTED.md)
- [App Store Mode](APP_STORE_MODE_IMPLEMENTATION.md)
- [Submission Guide](APP_STORE_SUBMISSION_GUIDE.md)
- [Review Checklist](APP_STORE_REVIEW_CHECKLIST.md)

### Contact

- **Issues**: GitHub Issues
- **Email**: [support email]
- **Documentation**: See docs/ directory

---

_Last Updated: February 9, 2026_  
_Version: 1.0 with APP_STORE_MODE_
