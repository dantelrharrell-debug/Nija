# AGENTS.md — AI Agent Instructions for NIJA

This file provides guidance for AI coding agents (GitHub Copilot, automated PR bots, etc.) working on this repository.

---

## Project Overview

NIJA is a production autonomous cryptocurrency trading bot. It connects to Coinbase Advanced Trade, Kraken, and OKX via their APIs and executes live trades with real capital. Errors in trading logic, risk management, or broker integration can cause direct financial loss.

**Every code change in this repository must be treated as affecting a live production system.**

---

## Repository Layout

```
/bot/                    # Core trading-bot runtime (Python package)
  trading_strategy.py    # TradingStrategy orchestration class (APEX v7.1)
  nija_apex_strategy_v71.py  # APEX V7.1 strategy implementation
  broker_integration.py  # Coinbase API integration layer
  risk_manager.py        # Risk management
  execution_engine.py    # Trade execution
  indicators.py          # Technical indicators (RSI, etc.)
  tradingview_webhook.py # TradingView webhook receiver
  apex_*.py              # APEX strategy sub-components
  *_patch.py             # Runtime hot-patch modules

/scripts/                # Operational and maintenance scripts
  production_bootstrap.sh          # Primary deployment start script
  canonical_runtime_launcher_v26.py  # Canonical Python entrypoint

/archive/                # Historical / deprecated files — do NOT import

main.py                  # Top-level Python entrypoint
bot.py                   # Package bootstrap shim
Dockerfile               # Container image (multi-stage, python:3.11-slim)
railway.json             # Railway deployment configuration
requirements.txt         # Pinned Python dependencies
runtime.txt              # Python version (3.11)
start.sh                 # Shell entrypoint (wraps production_bootstrap.sh)
```

---

## Canonical Runtime Path

```
scripts/production_bootstrap.sh
  → scripts/canonical_runtime_launcher_v26.py
    → main.py
      → bot.bot
        → bot.bot_main
```

Never change the entrypoint chain without a full audit of startup guards, writer-lock acquisition, and authority handshake.

---

## Hard Rules for All Agents

### 1. Never touch live-trading safety guards
The following must never be removed, weakened, or bypassed:
- Distributed Redis writer lock (`STRICT_REDIS_WRITER_LOCK`, `NIJA_REQUIRE_REDIS_FOR_LIVE`)
- Writer authority heartbeat and generation checks
- Capital readiness gate (`CAPITAL_READINESS_HANDOFF_V34_READY`)
- Broker connectivity snapshot gate
- Risk-management position-size limits
- Minimum notional / minimum trade checks
- Fail-closed emergency-stop paths

### 2. Never commit secrets or bypass flags
- Do **not** commit `.env`, `*.pem`, or any file containing API keys / secrets.
- Do **not** set these environment variables to unsafe values in committed code:
  - `NIJA_UNSAFE_BYPASS_DISTRIBUTED_LOCK=true`
  - `NIJA_DISABLE_WRITER_LOCK=true`
  - `FORCE_TRADE=true` (in production paths)
  - `NIJA_CONFIRM_BYPASS_RISKS=true`
  - `NIJA_SKIP_STARTUP_PHASE_GATE`
- Run `runtime-tools-secret_scanning` on every changed file before committing.

### 3. Never modify trading logic without a backtest
Changes to strategy entry/exit conditions, RSI parameters, trailing-stop logic, or position sizing require a backtest. Document results in the PR description.

### 4. Never import from `/archive/`
Files in `/archive/` are historical references only. They may contain outdated or broken logic.

### 5. Preserve working code
Do not remove functional implementations. Prefer additive changes. If replacing a module, keep the old version under a versioned name until the replacement is proven in production.

---

## Python Coding Standards

| Concern | Rule |
|---|---|
| Naming | `snake_case` for variables/functions/files; `PascalCase` for classes |
| Style | PEP 8; 4-space indentation; max 120-char lines |
| Type hints | Required for all new public function signatures |
| Docstrings | Required for all classes and public functions |
| Error handling | Wrap all external API calls in `try/except`; log errors with context; never log secrets |
| Imports | No circular imports; group stdlib → third-party → local |
| Logging | Use the `logging` module; never use `print` in bot runtime code |

---

## Dependency Management

- All dependencies are in `requirements.txt` with **pinned versions**.
- Python version is **3.11** (see `runtime.txt`).
- Before adding a new dependency, run `runtime-tools-gh-advisory-database` to check for known CVEs.
- Do **not** add new dependencies unless strictly necessary.

Key packages:
| Package | Purpose |
|---|---|
| `coinbase-advanced-py==1.8.2` | Coinbase Advanced Trade API |
| `flask>=3.0,<4.0` | Webhook server |
| `pandas` / `numpy` | Data analysis and indicators |
| `redis` | Distributed writer lock and authority heartbeat |
| `boto3` | AWS Secrets Manager backend (optional) |

---

## Environment Variables

Secrets are read from the environment (Railway injects them; locally use `.env`).

Required secrets (never commit these):
- `COINBASE_API_KEY`
- `COINBASE_API_SECRET`
- `COINBASE_PEM_CONTENT`
- `KRAKEN_API_KEY` / `KRAKEN_API_SECRET`
- `OKX_API_KEY` / `OKX_API_SECRET` / `OKX_PASSPHRASE`
- `REDIS_URL`

Key operational variables (set in `railway.json`; review before overriding):
- `NIJA_REQUIRE_REDIS_FOR_LIVE=true`
- `STRICT_REDIS_WRITER_LOCK=true`
- `NIJA_FAIL_CLOSED_EXIT_ON_UNREACHABLE_REDIS=true`
- `NIJA_MIN_CASH_RESERVE_USD`, `MIN_NOTIONAL_USD`, `MIN_TRADE_USD`

---

## Validation Before Every Commit

1. **Syntax check** all modified `.py` files:
   ```bash
   python -m py_compile <changed_file>.py
   ```
2. **Secret scan** all modified files using `runtime-tools-secret_scanning`.
3. **CodeQL check** using `codeql_checker` (not trivial if trading logic changed).
4. Confirm the following flags are **NOT** present in committed code at unsafe values:
   - `NIJA_UNSAFE_BYPASS_DISTRIBUTED_LOCK`
   - `NIJA_DISABLE_WRITER_LOCK`
   - `NIJA_SKIP_STARTUP_PHASE_GATE`

---

## PR Checklist

When opening a PR, follow `.github/pull_request_template.md`. Minimally verify:

- [ ] `python -m py_compile` clean on all changed `.py` files
- [ ] No bypass flags committed
- [ ] Authority-gate denials are NOT recorded as exchange order rejections (kill-switch feedback loop invariant preserved)
- [ ] For trading logic changes: strategy change backtested before live deployment
- [ ] Secret scan passed
- [ ] CI checks pass

---

## Areas Requiring Extra Caution

| Area | Why |
|---|---|
| `bot/trading_strategy.py` | Orchestrates live order flow; past IndentationErrors caused outages |
| `bot/broker_integration.py` | Direct exchange connectivity; bugs can cause failed/duplicate orders |
| `bot/risk_manager.py` | Controls position sizes and stop-losses; bugs risk capital loss |
| `bot/authority_heartbeat*.py` | Writer-lock heartbeat; must remain fail-closed |
| `scripts/production_bootstrap.sh` | Deployment entrypoint; errors prevent the bot from starting |
| `railway.json` | Controls deployed environment variables including safety flags |

---

## What Agents Should and Should Not Do

### Safe to delegate
- Bug fixes (syntax, indentation, exception handling)
- Adding or improving logging
- Refactoring for clarity (no logic change)
- Documentation updates
- Test coverage improvements
- Dependency security patches (with advisory check)

### Requires human review before merging
- Any change to trading strategy entry/exit logic
- Risk management parameter changes
- Writer-lock, authority heartbeat, or Redis guard modifications
- Broker API integration changes
- Changes to startup / bootstrap sequence
- Security-sensitive code (webhook signature validation, secret handling)

### Never do
- Remove or soften safety guards
- Commit secrets or unsafe bypass flags
- Import from `/archive/`
- Merge without passing CI and secret scan

---

## Deployment

- Platform: **Railway** (primary), Render (secondary)
- Container: Docker (`python:3.11-slim`)
- Start command: `bash scripts/production_bootstrap.sh`
- Health check: `GET /healthz`
- Replicas: 1 (single-writer enforced by Redis distributed lock)
- Restart policy: `ON_FAILURE`, max 3 retries

To deploy: push to `main`. Railway auto-deploys on push.

---

## Contacts and References

- `README.md` — Current production state and recovery checkpoint
- `APEX_V71_DOCUMENTATION.md` — APEX V7.1 strategy details
- `BROKER_INTEGRATION_GUIDE.md` — Exchange integration guide
- `TRADINGVIEW_SETUP.md` — TradingView webhook setup
- `.github/copilot-instructions.md` — Copilot-specific coding instructions
