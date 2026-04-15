# Dead Code Archive — April 2026

These files were moved here as part of **NIJA Production Stabilization Plan v1**
(April 15, 2026).  They were confirmed never-imported by any other `bot/` module
(orphan scan across all 188 orphaned files; 19 selected here as the highest-risk
duplicates).

## Why they were archived (not deleted)

Per the plan's safety rule:
> Move to `archive/` before deleting from `bot/`, never delete live until system is verified stable.

If the production system is stable after 2+ weeks of live trading, these files
may be permanently deleted.

## Files archived

### Capital modules (9 files)
| File | Reason |
|------|--------|
| `advanced_capital_engine.py` | Never imported; superseded by `capital_authority.py` |
| `automated_capital_throttle.py` | Never imported; duplicate throttle logic |
| `capital_domain_registry.py` | Never imported; orphaned registry concept |
| `capital_protection_layer.py` | Never imported; superseded by CA reserve logic |
| `capital_scaling_triggers.py` | Never imported; dead trigger system |
| `enhanced_capital_scaling.py` | Never imported; duplicate scaling math |
| `integrated_capital_optimizer.py` | Never imported; dead integration wrapper |
| `small_capital_manager.py` | Never imported; micro-account logic in `fee_aware_config.py` |
| `user_capital_isolation_engine.py` | Never imported; isolation handled by `account_isolation_manager.py` |

### Risk modules (5 files)
| File | Reason |
|------|--------|
| `dynamic_risk_engine.py` | Only linked from `capital_strategy_selector` (itself dead-path); active engine is `risk_engine.py` / `core/tiered_risk_engine.py` |
| `portfolio_risk_tuner.py` | Never imported |
| `risk_acknowledgement.py` | Never imported; UI/compliance concept never wired |
| `risk_freeze_guard.py` | Never imported; freeze logic handled in `position_manager.py` |
| `risk_parity_engine.py` | Never imported; parity math unused |

### APEX strategy files (4 files)
| File | Reason |
|------|--------|
| `apex_crash_resilient_integration.py` | Never imported; old integration wrapper |
| `apex_example.py` | Never imported; example/demo file |
| `apex_live_trading.py` | Never imported; superseded by `nija_apex_strategy_v71.py` |
| `nija_apex_strategy_v8.py` | Never imported; superseded by v71 |

### Position sizer (1 file)
| File | Reason |
|------|--------|
| `optimized_position_sizer.py` | Only used by `integrated_capital_optimizer.py` (also archived above); active sizer is `position_sizer.py` |

## DO NOT ARCHIVE (protected core files)
```
bot/capital_authority.py
bot/multi_account_broker_manager.py
bot/broker_manager.py
bot/broker_registry.py
bot/global_kraken_nonce.py
bot/execution_engine.py
bot/position_sizer.py
bot/risk_engine.py
core/tiered_risk_engine.py
```
