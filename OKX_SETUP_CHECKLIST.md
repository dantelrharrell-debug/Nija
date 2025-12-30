# ✅ OKX Trading Setup Checklist

Use this checklist to set up OKX trading step by step.

## 📋 Pre-Trading Checklist

### ☐ Phase 1: Account Setup (5 min)

- [ ] Create OKX account
  - [ ] Testnet: https://www.okx.com/testnet (recommended first)
  - [ ] Live: https://www.okx.com
- [ ] Verify email address
- [ ] Enable 2FA (Two-Factor Authentication)

### ☐ Phase 2: API Credentials (5 min)

- [ ] Log into OKX account
- [ ] Navigate to Account → API
- [ ] Create new API key
  - [ ] Name: "NIJA Trading Bot"
  - [ ] Permissions: ✅ Trade ONLY (NOT Withdrawal)
  - [ ] IP Whitelist: Add your server IP (optional)
  - [ ] Create passphrase (save it!)
- [ ] Save credentials securely:
  - [ ] API Key: ________________
  - [ ] API Secret: ________________
  - [ ] Passphrase: ________________

⚠️ **IMPORTANT**: You'll only see these once! Save them now!

### ☐ Phase 3: Environment Configuration (2 min)

- [ ] Navigate to NIJA directory
  ```bash
  cd /path/to/Nija
  ```

- [ ] Copy environment template
  ```bash
  cp .env.example .env
  ```

- [ ] Edit `.env` file
  ```bash
  nano .env  # or use your favorite editor
  ```

- [ ] Add OKX credentials:
  ```bash
  OKX_API_KEY=your_api_key_here
  OKX_API_SECRET=your_secret_key_here
  OKX_PASSPHRASE=your_passphrase_here
  OKX_USE_TESTNET=true  # Set to false for live trading
  ```

- [ ] Save and close file

- [ ] Verify `.env` is in `.gitignore`
  ```bash
  grep "^\.env$" .gitignore
  ```

### ☐ Phase 4: Installation & Testing (3 min)

- [ ] Install dependencies
  ```bash
  pip install okx python-dotenv
  ```

- [ ] Run validation script
  ```bash
  python validate_okx_readiness.py
  ```
  - [ ] Verify: "✅ OKX IS FULLY READY FOR TRADING!"

- [ ] Test connection
  ```bash
  python test_okx_connection.py
  ```
  - [ ] Verify: "✅ All tests passed!"

### ☐ Phase 5: First Test Trade (5 min) - TESTNET ONLY

- [ ] Verify testnet mode is enabled
  ```bash
  grep "OKX_USE_TESTNET=true" .env
  ```

- [ ] Check balance
  ```bash
  python -c "from bot.broker_manager import OKXBroker; okx=OKXBroker(); okx.connect(); print(f'Balance: \${okx.get_account_balance():.2f}')"
  ```

- [ ] Place small test order ($5-10)
  ```python
  from bot.broker_manager import OKXBroker
  okx = OKXBroker()
  okx.connect()
  order = okx.place_market_order('BTC-USDT', 'buy', 10.0)
  print(f"Order ID: {order['order_id']}")
  ```

- [ ] Verify order was placed
  - [ ] Check OKX testnet website
  - [ ] Check positions: `okx.get_positions()`

- [ ] Place sell order to close
  ```python
  # Get current BTC position size
  positions = okx.get_positions()
  btc_pos = [p for p in positions if p['symbol'] == 'BTC-USDT'][0]
  # Sell it
  okx.place_market_order('BTC-USDT', 'sell', btc_pos['quantity'])
  ```

### ☐ Phase 6: Security Review (2 min)

- [ ] API key has "Trade" permission ONLY (not "Withdrawal")
- [ ] IP whitelist is enabled (recommended)
- [ ] `.env` file is NOT committed to git
- [ ] 2FA is enabled on OKX account
- [ ] Credentials are stored securely
- [ ] Using testnet for all testing

### ☐ Phase 7: Documentation Review (10 min)

- [ ] Read [OKX_QUICK_REFERENCE.md](OKX_QUICK_REFERENCE.md)
- [ ] Read [OKX_SETUP_GUIDE.md](OKX_SETUP_GUIDE.md)
- [ ] Read [OKX_TRADING_READINESS_STATUS.md](OKX_TRADING_READINESS_STATUS.md)
- [ ] Bookmark troubleshooting section in setup guide

---

## 🚀 Ready for Live Trading? (After Testnet Success)

### ☐ Phase 8: Go Live (10 min) - CAREFUL!

- [ ] Create LIVE OKX account (if using testnet before)
- [ ] Generate LIVE API credentials
  - [ ] Trade permission ONLY
  - [ ] Enable IP whitelist
- [ ] Update `.env` file:
  ```bash
  OKX_API_KEY=live_api_key_here
  OKX_API_SECRET=live_secret_here
  OKX_PASSPHRASE=live_passphrase_here
  OKX_USE_TESTNET=false  # ← CHANGED TO FALSE
  ```

- [ ] Verify live mode
  ```bash
  python test_okx_connection.py
  # Check output says "LIVE" not "TESTNET"
  ```

- [ ] Deposit small amount to OKX trading account ($50-100)
- [ ] Test with VERY SMALL order ($5-10)
- [ ] Monitor for 24 hours
- [ ] Gradually increase if successful

---

## ⚠️ Safety Rules

### ❌ NEVER:
- [ ] ❌ Enable "Withdrawal" permission
- [ ] ❌ Share API credentials
- [ ] ❌ Commit `.env` to git
- [ ] ❌ Skip testnet testing
- [ ] ❌ Trade with money you can't afford to lose
- [ ] ❌ Use live mode without testing first

### ✅ ALWAYS:
- [ ] ✅ Test on testnet first
- [ ] ✅ Start with small amounts
- [ ] ✅ Enable IP whitelist
- [ ] ✅ Monitor trading activity
- [ ] ✅ Keep credentials secure
- [ ] ✅ Read documentation

---

## 📊 Quick Status Check

Run this anytime to verify OKX is ready:

```bash
python validate_okx_readiness.py
```

Expected output: "🎉 ✅ OKX IS FULLY READY FOR TRADING!"

---

## 🆘 Troubleshooting

### Problem: "Invalid signature" error
**Solution**:
- [ ] Double-check API credentials in `.env`
- [ ] Ensure no extra spaces in credentials
- [ ] Verify using correct environment (testnet vs live)

### Problem: "Insufficient balance" error
**Solution**:
- [ ] Check balance: `okx.get_account_balance()`
- [ ] Testnet: Request test tokens
- [ ] Live: Transfer funds to trading account

### Problem: "Module not found: okx"
**Solution**:
- [ ] Install SDK: `pip install okx`

### Problem: "Order size too small"
**Solution**:
- [ ] Use at least $5-10 USD per order
- [ ] Check minimum order size for the pair

---

## 📈 Success Metrics

After completing this checklist, you should have:

- [x] OKX account created
- [x] API credentials generated and saved
- [x] Environment configured
- [x] All tests passing
- [x] Successful test trades on testnet
- [x] Security measures in place
- [x] Documentation reviewed
- [x] Ready to trade!

---

## 🎓 Next Steps After Setup

1. **Read Strategy Docs**: [APEX_V71_DOCUMENTATION.md](APEX_V71_DOCUMENTATION.md)
2. **Understand Risk Management**: [BROKER_INTEGRATION_GUIDE.md](BROKER_INTEGRATION_GUIDE.md)
3. **Run Backtests**: Test your strategy before live deployment
4. **Monitor Performance**: Track wins/losses, adjust parameters
5. **Scale Gradually**: Increase position sizes slowly

---

## ✅ Final Checklist

Before you start automated trading:

- [ ] All testnet tests successful
- [ ] Documentation read and understood
- [ ] Security measures in place
- [ ] Small live test completed successfully
- [ ] Monitoring system in place
- [ ] Risk management understood
- [ ] Emergency stop plan ready

---

**Estimated Total Time**: 30-45 minutes (including testing)

**Difficulty**: Easy (just follow steps)

**Risk Level**: Low (if using testnet first)

**Ready?** Start with Phase 1! ⬆️

---

**Last Updated**: December 30, 2024  
**Status**: Ready to use  
**Version**: 1.0
