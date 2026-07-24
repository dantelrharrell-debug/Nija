# Canonical Startup Recovery v26

## Root cause

The documented production path is `scripts/render_entrypoint.sh -> scripts/production_bootstrap.sh -> start.sh -> main.py -> bot.bot -> bot.bot_main`.

The v22/v24 canonical broker bootstrap code was present, but a late import could allow `bot.bot_main` to load before the convergence hook wrapped writer acquisition. In that ordering, the process could own a writer fencing token while `MultiAccountBrokerManager._fsm_initialized` remained false. The downstream symptoms were:

- `broker_manager_not_initialized`
- `hydrated=False`
- `capital=$0.00`
- `stale=True`
- `brokers=0`
- `LIVE_PENDING_CONFIRMATION`
- `NIJA_RUNTIME_EXECUTION_AUTHORITY=0`
- `cycles=0`

## Repair

Render now patches `start.sh` to launch:

```text
scripts/canonical_runtime_launcher_v26.py
```

The launcher loads and installs `canonical_broker_startup_convergence_v24.py` directly from its file path before importing `main.py` or any `bot` package module. It fails closed if `bot.bot_main` was already imported or if the v24 installer does not attest successful installation.

## Required startup proof

```text
CANONICAL_RUNTIME_LAUNCHER_V26_READY
CANONICAL_BROKER_STARTUP_CONVERGENCE_V24_INSTALLED
PREBOT_WRITER_AUTHORITY_READY
ENTRYPOINT_WRITER_AUTHORITY_READY
ENTRYPOINT_WRITER_AUTHORITY_VERIFIED
CANONICAL_BROKER_PREBOOTSTRAP_V22_READY
CANONICAL_BROKER_STARTUP_CONVERGENCE_V24_READY
```

Capital and execution must then independently prove:

```text
hydrated=True
stale=False
capital=<positive amount>
brokers>=1
NIJA_RUNTIME_TRADING_STATE=LIVE_ACTIVE
NIJA_RUNTIME_EXECUTION_AUTHORITY=1
cycles>0
```

This repair does not grant writer authority, force broker connectivity, fabricate balances, force activation, bypass risk controls, or guarantee trades or profits.
