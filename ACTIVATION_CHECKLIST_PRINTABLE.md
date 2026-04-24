# ✅ Multi-User Trading Activation - Visual Checklist

> **Print this page** and check off items as you complete them. For details, see `MULTI_USER_TRADING_ACTIVATION_CHECKLIST.md`

---

## 🔧 PHASE 1: Environment Setup

### Repository & Dependencies
- [ ] Python 3.11+ installed: `python --version`
- [ ] Repository cloned: `git clone https://github.com/dantelrharrell-debug/Nija.git`
- [ ] Dependencies installed: `pip install -r requirements.txt`

### Environment Variables
- [ ] `.env` file created from `.env.example`
- [ ] JWT_SECRET_KEY generated (32+ chars)
- [ ] POSTGRES_PASSWORD generated (if using PostgreSQL)
- [ ] DATABASE_URL configured
- [ ] LIVE_CAPITAL_VERIFIED set to `false` initially
- [ ] DRY_RUN_MODE set to `true` initially

**Command to generate secrets**:
```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

---

## 🔌 PHASE 2: Broker Credentials

### Kraken Platform Account (REQUIRED)
- [ ] Kraken account created/verified
- [ ] Classic API key generated (NOT OAuth)
- [ ] Permissions: Query + Trade only (NO withdrawal)
- [ ] `KRAKEN_PLATFORM_API_KEY` in `.env`
- [ ] `KRAKEN_PLATFORM_API_SECRET` in `.env`

### Kraken User Accounts (Optional)
For each user:
- [ ] User has Kraken account
- [ ] API key generated with correct permissions
- [ ] `KRAKEN_USER_{FIRSTNAME}_API_KEY` in `.env`
- [ ] `KRAKEN_USER_{FIRSTNAME}_API_SECRET` in `.env`

### Alpaca (Optional)
- [ ] `ALPACA_API_KEY` in `.env`
- [ ] `ALPACA_API_SECRET` in `.env`
- [ ] `ALPACA_PAPER` set to `true` for testing

---

## 👥 PHASE 3: User Configuration

### User Config Files
- [ ] Edit `config/users/retail_kraken.json` (or appropriate file)
- [ ] All users have unique `user_id`
- [ ] All users have `enabled: true`
- [ ] `broker_type` matches broker (kraken/alpaca)
- [ ] `user_id` matches env var pattern (e.g., `john_doe` → `JOHN`)

**Example user**:
```json
{
  "user_id": "john_doe",
  "name": "John Doe",
  "account_type": "retail",
  "broker_type": "kraken",
  "enabled": true
}
```

---

## 💾 PHASE 4: Database Setup

### PostgreSQL (Production)
- [ ] PostgreSQL 15+ installed
- [ ] Database created: `CREATE DATABASE nija;`
- [ ] User created with permissions
- [ ] `DATABASE_URL` in `.env` (PostgreSQL format)
- [ ] Schema initialized: `python init_database.py`

### SQLite (Development)
- [ ] `DATABASE_URL=sqlite:///nija.db` in `.env`
- [ ] Schema initialized: `python init_database.py`
- [ ] `nija.db` file exists

### Redis (Optional)
- [ ] Redis installed and running
- [ ] Can ping: `redis-cli ping` → `PONG`
- [ ] `REDIS_URL` in `.env` (if using)

---

## 🛡️ PHASE 5: Safety & Security

### Kill Switch
- [ ] Kill switch tested: `python emergency_kill_switch.py`
- [ ] Kill switch accessible in emergency
- [ ] Reset procedure documented

### Security Audit
- [ ] No API keys in code: `grep -r "sk_live_" .`
- [ ] `.env` in `.gitignore`
- [ ] `vault.db` in `.gitignore` (if using)
- [ ] Passwords are strong (32+ chars)
- [ ] API keys have minimal permissions

### Risk Management
- [ ] Position size limits configured per tier
- [ ] Daily loss limits understood
- [ ] Stop losses mandatory
- [ ] Max concurrent positions set

---

## 🧪 PHASE 6: Testing

### Dry Run Test (CRITICAL)
- [ ] `DRY_RUN_MODE=true` in `.env`
- [ ] `LIVE_CAPITAL_VERIFIED=false` in `.env`
- [ ] Start bot: `python bot.py`
- [ ] Platform account connects ✅
- [ ] All user accounts connect ✅
- [ ] "DRY RUN MODE" shown in logs
- [ ] No errors in output
- [ ] Run for at least 1 hour

### Paper Trading (CRITICAL)
- [ ] `DRY_RUN_MODE=false` but `ALPACA_PAPER=true` (if Alpaca)
- [ ] Run for 24 hours
- [ ] Orders simulated correctly
- [ ] Positions tracked correctly
- [ ] P&L calculated correctly
- [ ] No API errors

### Integration Tests
- [ ] Run: `python test_user_independent_trading.py`
- [ ] Run: `python test_account_isolation.py`
- [ ] All tests pass ✅

---

## 📊 PHASE 7: Monitoring

### Logging
- [ ] `logs/` directory exists
- [ ] Logs being written
- [ ] Log rotation configured (production)
- [ ] Log level appropriate (INFO)

### Health Checks
- [ ] Health endpoint works: `curl http://localhost:8000/health`
- [ ] Monitoring script created
- [ ] Alerts configured (email/Slack)

### Performance
- [ ] Order execution < 500ms
- [ ] API response < 1 second
- [ ] Database queries < 100ms
- [ ] Memory usage stable
- [ ] No rate limiting issues

---

## 🚀 PHASE 8: Deployment

### Docker (Optional)
- [ ] `docker build -t nija-bot .` succeeds
- [ ] Docker Compose: `docker-compose up -d`
- [ ] All services healthy
- [ ] Health check passing

### Railway (Optional)
- [ ] Railway project created
- [ ] All env vars set in Railway dashboard
- [ ] Database provisioned
- [ ] Deployment successful
- [ ] Logs show bot running

### Production
- [ ] All production env vars set
- [ ] HTTPS/TLS enabled
- [ ] Firewall configured
- [ ] Backups configured
- [ ] Domain configured (if needed)

---

## ✈️ PHASE 9: Go-Live

### Pre-Go-Live (48 hours before)
- [ ] All accounts funded
- [ ] All credentials verified
- [ ] 24+ hours dry run passed
- [ ] Paper trading results reviewed
- [ ] Team trained
- [ ] Emergency procedures documented

### Go-Live Day
- [ ] Set `LIVE_CAPITAL_VERIFIED=true`
- [ ] Set `DRY_RUN_MODE=false`
- [ ] Start with platform account only (1 hour)
- [ ] Enable user 1 (monitor 1 hour)
- [ ] Enable user 2 (monitor 1 hour)
- [ ] Enable all users
- [ ] Monitor for 24 hours intensively

### Post-Go-Live
- [ ] First trade executed successfully ✅
- [ ] All positions tracked ✅
- [ ] Stop losses set automatically ✅
- [ ] No critical errors ✅
- [ ] 24-hour review scheduled
- [ ] 1-week review scheduled
- [ ] 1-month review scheduled

---

## 🔄 PHASE 10: Operations

### Daily Checklist
- [ ] Check logs for overnight issues
- [ ] Verify all accounts connected
- [ ] Review positions opened/closed
- [ ] Check P&L per user
- [ ] Verify no API errors
- [ ] Check system resources

### Weekly Checklist
- [ ] Review all user performance
- [ ] Check risk limit adherence
- [ ] Database maintenance
- [ ] Test backup restoration
- [ ] Review logs for warnings

### Monthly Checklist
- [ ] Comprehensive performance review
- [ ] Security audit
- [ ] Update dependencies
- [ ] Test disaster recovery
- [ ] Review monitoring effectiveness

---

## 🚨 Emergency Procedures

### Stop All Trading
```bash
python emergency_kill_switch.py
```

### Check Kill Switch Status
```bash
python -c "from bot.kill_switch import get_kill_switch; ks = get_kill_switch(); print('DISABLED' if ks.is_trading_disabled() else 'ACTIVE')"
```

### Close All Positions
```bash
python -c "from bot.execution_engine import force_close_all_positions; force_close_all_positions()"
```

### Rollback to Dry Run
```bash
export DRY_RUN_MODE=true
export LIVE_CAPITAL_VERIFIED=false
python bot.py
```

---

## ✅ FINAL SIGN-OFF

### Team Approvals
- [ ] **Engineering**: Systems operational, no critical bugs
  - Signed: _________________ Date: _________

- [ ] **Operations**: Monitoring configured, procedures ready
  - Signed: _________________ Date: _________

- [ ] **Security**: Audit passed, credentials secured
  - Signed: _________________ Date: _________

- [ ] **Trading/Product**: Risk limits appropriate
  - Signed: _________________ Date: _________

### Success Criteria (ALL MUST BE ✅)
- [ ] Platform account trading live
- [ ] All user accounts enabled and trading
- [ ] All positions tracked correctly
- [ ] Stop losses set automatically
- [ ] No critical errors in 24 hours
- [ ] Monitoring and alerts working
- [ ] Emergency procedures accessible
- [ ] Team trained and ready

---

## 🎉 SYSTEM STATUS: 100% OPERATIONAL

**Congratulations!** NIJA is fully operational for multi-user trading.

---

## 📞 Quick Reference

| Need | Command/File |
|------|--------------|
| Start bot | `python bot.py` |
| Emergency stop | `python emergency_kill_switch.py` |
| Health check | `curl http://localhost:8000/health` |
| View logs | `tail -f logs/nija.log` |
| User config | `config/users/retail_kraken.json` |
| Environment | `.env` |
| Full checklist | `MULTI_USER_TRADING_ACTIVATION_CHECKLIST.md` |
| Quick start | `QUICK_START_MULTI_USER.md` |

---

**Date Completed**: _______________
**Operator**: _______________
**System Version**: _______________

---

*Keep this checklist for reference and future activations*
