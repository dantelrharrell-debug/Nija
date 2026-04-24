# NIJA Architecture Guarantees

## Core Architectural Commitments

NIJA's architecture provides two fundamental guarantees that ensure fair, independent, and reliable trading for all users:

### 1. Independent Trading is Enforced by Config + Tests

**Guarantee:** Every user account trades independently using their own analysis, execution, and position management. No copy trading or trade mirroring occurs.

**How It's Enforced:**

- **Configuration:** User configs explicitly set `independent_trading: true` (see `config/users/*.json`)
  - Each user has separate trading threads
  - Position sizing is scaled to individual account balances
  - Risk management is applied per account
  
- **Code Architecture:** 
  - Separate broker dictionaries: `platform_brokers` vs `user_brokers`
  - Account type tagging on every broker instance
  - Independent trading loops per user thread

- **Test Coverage:**
  - `test_user_independent_trading.py` - Validates independent_trading field handling
  - `test_decoupling_integration.py` - Verifies user threads start independently
  - `bot/tests/test_platform_user_separation.py` - Proves platform trades never execute on user brokers

**Documentation:** See [INDEPENDENT_TRADING_NO_COPY.md](INDEPENDENT_TRADING_NO_COPY.md) for full details.

### 2. Platform Status Cannot Gate User Execution

**Guarantee:** User trading threads operate independently of platform connection status. If a user's broker is connected and the user has `independent_trading: true`, their thread runs regardless of platform state.

**How It's Enforced:**

- **Configuration:** User threads check `independent_trading` flag, not platform status
  - Users with `independent_trading: true` always get their own trading thread
  - Platform disconnect does not stop user trading threads
  
- **Code Architecture:**
  - User threads are started based on: `user.enabled AND user.independent_trading`
  - Platform broker status is not checked for user thread startup
  - User position management continues even if platform is offline

- **Test Coverage:**
  - `test_decoupling_integration.py` - Verifies user threads start regardless of platform status
  - `bot/tests/test_platform_user_separation.py` - Validates complete isolation between platform and user operations

**Documentation:** See [PLATFORM_USER_SEPARATION_VERIFICATION.md](PLATFORM_USER_SEPARATION_VERIFICATION.md) for verification details.

## Architecture Diagram

```
┌────────────────────────────────────────────────────────┐
│              NIJA APEX v7.1 Strategy                   │
│         (RSI + Volatility + Confidence)                │
└────────────────────────────────────────────────────────┘
                         │
         ┌───────────────┼───────────────┐
         ▼               ▼               ▼
   ┌──────────┐    ┌──────────┐    ┌──────────┐
   │ Platform │    │  User 1  │    │  User 2  │
   │  Thread  │    │  Thread  │    │  Thread  │
   │ (OPTIONAL)│   │(INDEPENDENT)│ │(INDEPENDENT)│
   └──────────┘    └──────────┘    └──────────┘
         │               │               │
         ▼               ▼               ▼
   [Platform]      [User Broker]   [User Broker]
   [Broker]        [Connected]     [Connected]
   [Status = ❌]   [Status = ✅]   [Status = ✅]
         │               │               │
         X          Trades ✅        Trades ✅
   (Offline)      (Independent)   (Independent)
```

**Key Insight:** User threads execute independently. Platform status affects only platform trading, never user trading.

## Verification

All guarantees are continuously verified through:

1. **Unit Tests** - Test individual components in isolation
2. **Integration Tests** - Test cross-component behavior
3. **Configuration Validation** - Enforce required config fields
4. **Runtime Logging** - "User positions excluded from platform caps" appears in logs

Run verification tests:

```bash
# Independent trading tests
python test_user_independent_trading.py

# Decoupling integration tests
python test_decoupling_integration.py

# Platform/user separation tests
python bot/tests/test_platform_user_separation.py
```

## Summary

✅ **Independent trading:** Enforced by configuration flags and validated by comprehensive test suite  
✅ **Platform isolation:** User execution cannot be gated by platform status  
✅ **Continuous verification:** Architecture guarantees are tested on every code change

These guarantees ensure that NIJA provides fair, reliable, and independent trading for all users regardless of platform state.
