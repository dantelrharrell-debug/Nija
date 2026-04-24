# NIJA Lifecycle & Thread Behavior - Visual Verification Guide

## Overview

This document provides a complete visual map of NIJA's lifecycle, showing every exit point, thread behavior, and state transition with their corresponding log markers.

## Lifecycle Flow Diagram

```
┌──────────────────────────────────────────────────────────────────┐
│                    NIJA PROCESS STARTUP                           │
│  ╔════════════════════════════════════════════════════════════╗  │
│  ║        🚀 NIJA TRADING BOT STARTUP                         ║  │
│  ║  Process ID, Python Version, Working Directory             ║  │
│  ╚════════════════════════════════════════════════════════════╝  │
└──────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────────┐
│              EMERGENCY STOP CHECK (Top-Level)                     │
│  ┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓  │
│  ┃ 🚨 EXIT POINT - EMERGENCY STOP FILE DETECTED           ┃  │
│  ┃ Exit Code: 0 | PID: xxxxx                              ┃  │
│  ┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛  │
└──────────────────────────────────────────────────────────────────┘
                              │ (if EMERGENCY_STOP file NOT present)
                              ▼
┌──────────────────────────────────────────────────────────────────┐
│                SIGNAL HANDLERS REGISTRATION                       │
│  ✅ Signal handlers registered (SIGTERM, SIGINT)                 │
└──────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────────┐
│               HEALTH CHECK MANAGER INITIALIZATION                 │
│  ✅ Health check manager initialized                             │
└──────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────────┐
│              HEARTBEAT THREAD STARTUP (Daemon)                    │
│  ╔════════════════════════════════════════════════════════════╗  │
│  ║       ✅ BACKGROUND THREADS STARTED                        ║  │
│  ║  HeartbeatWorker: Thread ID xxxxx                          ║  │
│  ║  Update Interval: 10 seconds                               ║  │
│  ║  Thread is alive: True                                     ║  │
│  ╚════════════════════════════════════════════════════════════╝  │
│                                                                   │
│  🧵 Heartbeat thread running continuously:                       │
│     - Updates heartbeat every 10 seconds                         │
│     - Logs status every 60 heartbeats (10 minutes)               │
│     - Daemon thread (won't prevent process exit)                 │
└──────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────────┐
│            EXCHANGE CREDENTIALS VALIDATION                        │
│  Checks: Kraken, Coinbase, OKX, Binance, Alpaca                 │
└──────────────────────────────────────────────────────────────────┘
                              │
                              ├─────────────────────────────────┐
                              │                                 │
                    No credentials                    Has credentials
                              │                                 │
                              ▼                                 ▼
┌──────────────────────────────────────┐    ┌──────────────────────────────────┐
│   CONFIG ERROR KEEP-ALIVE MODE       │    │   HEALTH SERVER STARTUP          │
│  ╔══════════════════════════════════╗│    │  🌐 Health server listening      │
│  ║ ⚠️ ENTERING CONFIG ERROR        ║│    │     on port xxxx                 │
│  ║    KEEP-ALIVE MODE               ║│    └──────────────────────────────────┘
│  ║  No credentials configured       ║│                    │
│  ║  Process stays alive             ║│                    ▼
│  ║  Heartbeat: 60s interval         ║│    ┌──────────────────────────────────┐
│  ║  Thread Status Report            ║│    │   TRADING STRATEGY INIT          │
│  ╚══════════════════════════════════╝│    │  Initialize brokers, accounts    │
│                                      │    └──────────────────────────────────┘
│  Infinite loop:                      │                    │
│  • Sleep 60s                         │                    ▼
│  • Heartbeat (manual)                │    ┌──────────────────────────────────┐
│  • Log status every 10 minutes       │    │   TRADING MODE SELECTION         │
│                                      │    │  Multi-broker or Single-broker   │
│  Exit on KeyboardInterrupt:          │    └──────────────────────────────────┘
│  ┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓  │                    │
│  ┃ ✅ EXIT POINT                ┃  │            ┌───────┴────────┐
│  ┃ Config error interrupted     ┃  │            │                │
│  ┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛  │   Multi-broker      Single-broker
└──────────────────────────────────────┘            │                │
                                                    ▼                ▼
                                    ┌────────────────────────────────────────┐
                                    │   INDEPENDENT MULTI-BROKER TRADING     │
                                    │  ╔═══════════════════════════════════╗ │
                                    │  ║ 🚀 STARTING INDEPENDENT          ║ │
                                    │  ║    MULTI-BROKER TRADING MODE     ║ │
                                    │  ╚═══════════════════════════════════╝ │
                                    │                                        │
                                    │  Trading loop (150s cycle):            │
                                    │  • Heartbeat (manual)                  │
                                    │  • Status every 10 cycles (25 min)     │
                                    │                                        │
                                    │  On KeyboardInterrupt:                 │
                                    │  ╔═══════════════════════════════════╗ │
                                    │  ║ ⚠️ TRADING LOOP INTERRUPTED      ║ │
                                    │  ║    Multi-Broker Mode              ║ │
                                    │  ║  Stopping all trading threads     ║ │
                                    │  ║  Thread Status Report             ║ │
                                    │  ╚═══════════════════════════════════╝ │
                                    └────────────────────────────────────────┘
                                                    │
                                                    │    ┌────────────────────┐
                                                    │    │ SINGLE-BROKER      │
                                                    │    │ TRADING            │
                                                    │    │                    │
                                                    │    │ Trading loop:      │
                                                    │    │ • Run cycle (150s) │
                                                    │    │ • Heartbeat        │
                                                    │    │                    │
                                                    │    │ On interrupt:      │
                                                    │    │ ╔═════════════════╗│
                                                    │    │ ║ ⚠️ INTERRUPTED ║│
                                                    │    │ ╚═════════════════╝│
                                                    │    └────────────────────┘
                                                    │                │
                                                    └────────────────┘
                                                            │
                                                            ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                      KEEP-ALIVE MODE (CRITICAL)                           │
│  ╔═══════════════════════════════════════════════════════════════════╗   │
│  ║                    🔒 ENTERING KEEP-ALIVE MODE                    ║   │
│  ║  Trading loops have exited, process will remain alive             ║   │
│  ║  Prevents Railway from restarting                                 ║   │
│  ║  Heartbeat maintained by heartbeat_worker thread (10s)            ║   │
│  ║  Status logging every 300s (5 minutes)                            ║   │
│  ║  Thread Status Report                                             ║   │
│  ╚═══════════════════════════════════════════════════════════════════╝   │
│                                                                           │
│  Infinite loop:                                                           │
│  • Sleep 300s (5 minutes)                                                 │
│  • Log status "💓 Keep-alive status check #N"                            │
│  • Every 12 iterations (1 hour): Full thread status report               │
│                                                                           │
│  On KeyboardInterrupt (UNEXPECTED):                                       │
│  ╔═══════════════════════════════════════════════════════════════════╗   │
│  ║         ⚠️ KEYBOARD INTERRUPT IN KEEP-ALIVE (UNEXPECTED)         ║   │
│  ║  Signal handlers should have intercepted SIGINT                   ║   │
│  ║  Continuing to stay alive as long-running worker                  ║   │
│  ╚═══════════════════════════════════════════════════════════════════╝   │
│  • Continues running (does NOT exit)                                      │
│                                                                           │
│  This loop runs FOREVER unless:                                           │
│  • SIGTERM/SIGINT signal received (handled by signal handler)             │
│  • Fatal exception in exception handler                                   │
└──────────────────────────────────────────────────────────────────────────┘
```

## Exit Points Reference

All exit points are now logged with distinctive visual markers:

### 1. Emergency Stop (Exit Code 0)
```
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ 🚨 EXIT POINT - EMERGENCY STOP FILE DETECTED                       ┃
┃ Exit Code: 0                                                       ┃
┃ PID: xxxxx                                                         ┃
┣━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┫
┃ Bot is disabled. See EMERGENCY_STOP file for details.             ┃
┃ Delete EMERGENCY_STOP file to resume trading.                     ┃
┃ This is an intentional shutdown (not a crash).                    ┃
┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛
```
**Triggered by:** EMERGENCY_STOP file present at startup  
**Expected:** Yes, intentional shutdown  
**Restart:** No

### 2. Signal Handler (Exit Code 0)
```
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ ✅ EXIT POINT - Signal SIGTERM received                            ┃
┃ Exit Code: 0                                                       ┃
┃ PID: xxxxx                                                         ┃
┣━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┫
┃ Graceful shutdown initiated by signal handler                     ┃
┃ This is an expected exit (not a crash)                            ┃
┃ Total Threads: 3                                                  ┃
┃   🔸 ✅ MainThread (ID: xxxxx)                                     ┃
┃   🔹 ✅ HeartbeatWorker (ID: xxxxx)                                ┃
┃   🔹 ✅ HealthServer (ID: xxxxx)                                   ┃
┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛
```
**Triggered by:** SIGTERM or SIGINT signal  
**Expected:** Yes, graceful shutdown  
**Restart:** Depends on platform policy (Railway: No with ON_FAILURE)

### 3. Configuration Error - KeyboardInterrupt (Exit Code 0)
```
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ ✅ EXIT POINT - Configuration error keep-alive interrupted         ┃
┃ Exit Code: 0                                                       ┃
┃ PID: xxxxx                                                         ┃
┣━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┫
┃ KeyboardInterrupt in config error keep-alive loop                 ┃
┃ No exchange credentials were configured                           ┃
┃ Total Threads: 2                                                  ┃
┃   🔸 ✅ MainThread (ID: xxxxx)                                     ┃
┃   🔹 ✅ HeartbeatWorker (ID: xxxxx)                                ┃
┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛
```
**Triggered by:** Ctrl+C while in config error keep-alive  
**Expected:** Unusual (should use signal handler)  
**Restart:** No

### 4. Broker Connection Failed (Exit Code 1)
```
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ ❌ EXIT POINT - Broker Connection Failed                           ┃
┃ Exit Code: 1                                                       ┃
┃ PID: xxxxx                                                         ┃
┣━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┫
┃ RuntimeError: Broker connection failed                            ┃
┃ Coinbase credentials not found or invalid                         ┃
┃ Check and set ONE of:                                             ┃
┃ 1. PEM File: COINBASE_PEM_PATH=/path/to/file.pem                  ┃
┃ ...                                                                ┃
┃ Total Threads: 3                                                  ┃
┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛
```
**Triggered by:** RuntimeError during broker initialization  
**Expected:** No, this is an error  
**Restart:** Yes (Railway restarts on failure up to 3 times)

### 5. Fatal Initialization Error (Exit Code 1)
```
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ ❌ EXIT POINT - Fatal Initialization Error                         ┃
┃ Exit Code: 1                                                       ┃
┃ PID: xxxxx                                                         ┃
┣━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┫
┃ RuntimeError: ...                                                  ┃
┃ Bot initialization failed                                         ┃
┃ Total Threads: 2                                                  ┃
┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛
```
**Triggered by:** Other RuntimeError during initialization  
**Expected:** No, this is an error  
**Restart:** Yes (Railway restarts on failure)

### 6. Unhandled Fatal Error (Exit Code 1)
```
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ ❌ EXIT POINT - Unhandled Fatal Error                              ┃
┃ Exit Code: 1                                                       ┃
┃ PID: xxxxx                                                         ┃
┣━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┫
┃ Exception Type: ValueError                                        ┃
┃ Error: ...                                                         ┃
┃ An unexpected error occurred                                      ┃
┃ Total Threads: 3                                                  ┃
┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛
```
**Triggered by:** Any unhandled exception  
**Expected:** No, this is an error  
**Restart:** Yes (Railway restarts on failure)

## Thread Lifecycle Reference

### HeartbeatWorker Thread (Daemon)

**Startup:**
```
╔══════════════════════════════════════════════════════════════════╗
║               ✅ BACKGROUND THREADS STARTED                      ║
╠══════════════════════════════════════════════════════════════════╣
║ HeartbeatWorker: Thread ID 139876543210                          ║
║ Update Interval: 10 seconds                                      ║
║ Thread is alive: True                                            ║
║ Health checks will be responsive to Railway (~30s interval)      ║
╚══════════════════════════════════════════════════════════════════╝

🧵 Heartbeat thread started (ID: 139876543210, Interval: 10s)
```

**Runtime Logging:**
- Every heartbeat (10s): Silent (no log)
- Every 60 heartbeats (10 minutes): `🧵 Heartbeat thread alive - 60 heartbeats sent` (DEBUG level)
- On error: `🧵 ❌ Error in heartbeat worker thread (ID: xxxxx): <error>`

**Behavior:**
- Daemon thread (won't prevent process exit)
- Runs infinite loop calling `health_manager.heartbeat()` every 10s
- Automatically terminates when main process exits
- Critical for Railway health check responsiveness

### HealthServer Thread (Daemon)

**Startup:**
```
🌐 Health server listening on port 5000
   📍 Liveness:  http://0.0.0.0:5000/health
   📍 Readiness: http://0.0.0.0:5000/ready
   📍 Status:    http://0.0.0.0:5000/status
   📍 Metrics:   http://0.0.0.0:5000/metrics
```

**Behavior:**
- Daemon thread running HTTP server
- Responds to health check requests from Railway
- Automatically calls `heartbeat()` on each `/health` request
- Automatically terminates when main process exits

### Independent Trading Threads (if multi-broker mode)

**Startup:**
- Logged by trading strategy (not in bot.py)
- Multiple threads, one per funded broker
- Non-daemon threads (can prevent exit if not stopped)

**Shutdown:**
- Explicitly stopped by `strategy.stop_independent_trading()` before trading loop breaks

## State Transitions

All major state transitions are marked with lifecycle banners:

### 1. Process Startup
```
╔══════════════════════════════════════════════════════════════════╗
║                  🚀 NIJA TRADING BOT STARTUP                     ║
╠══════════════════════════════════════════════════════════════════╣
║ Process ID: 12345                                                ║
║ Python Version: 3.11.0                                           ║
║ Working Directory: /app                                          ║
║ Initializing lifecycle management...                            ║
╚══════════════════════════════════════════════════════════════════╝
```

### 2. Background Threads Started
```
╔══════════════════════════════════════════════════════════════════╗
║               ✅ BACKGROUND THREADS STARTED                      ║
╠══════════════════════════════════════════════════════════════════╣
║ HeartbeatWorker: Thread ID 139876543210                          ║
║ Update Interval: 10 seconds                                      ║
║ Thread is alive: True                                            ║
║ Health checks will be responsive to Railway (~30s interval)      ║
╚══════════════════════════════════════════════════════════════════╝
```

### 3. Configuration Error Keep-Alive
```
╔══════════════════════════════════════════════════════════════════╗
║           ⚠️ ENTERING CONFIG ERROR KEEP-ALIVE MODE              ║
╠══════════════════════════════════════════════════════════════════╣
║ No exchange credentials configured - cannot trade               ║
║ Process will stay alive for health monitoring                   ║
║ Container will NOT restart automatically                        ║
║ Heartbeat interval: 60s                                          ║
║ Configure credentials and manually restart deployment           ║
║ Total Threads: 2                                                ║
║   🔸 ✅ MainThread (ID: xxxxx)                                   ║
║   🔹 ✅ HeartbeatWorker (ID: xxxxx)                              ║
╚══════════════════════════════════════════════════════════════════╝
```

### 4. Trading Loop Interrupted
```
╔══════════════════════════════════════════════════════════════════╗
║      ⚠️ TRADING LOOP INTERRUPTED - Multi-Broker Mode            ║
╠══════════════════════════════════════════════════════════════════╣
║ KeyboardInterrupt received in independent multi-broker loop     ║
║ Stopping all independent trading threads...                     ║
║ Completed 42 monitoring cycles                                  ║
║ Total Threads: 5                                                ║
║   🔸 ✅ MainThread (ID: xxxxx)                                   ║
║   🔹 ✅ HeartbeatWorker (ID: xxxxx)                              ║
║   🔹 ✅ Kraken-Trader (ID: xxxxx)                                ║
║   🔹 ✅ Coinbase-Trader (ID: xxxxx)                              ║
║   🔹 ✅ HealthServer (ID: xxxxx)                                 ║
╚══════════════════════════════════════════════════════════════════╝
```

### 5. Keep-Alive Mode Entry
```
╔══════════════════════════════════════════════════════════════════╗
║                   🔒 ENTERING KEEP-ALIVE MODE                    ║
╠══════════════════════════════════════════════════════════════════╣
║ Trading loops have exited, but process will remain alive        ║
║ This prevents Railway from restarting the service               ║
║ Heartbeat maintained by heartbeat_worker thread (10s)           ║
║ Status logging every 300s                                        ║
║ To shutdown: Use SIGTERM or SIGINT (handled by signal handlers) ║
║ Total Threads: 2                                                ║
║   🔸 ✅ MainThread (ID: xxxxx)                                   ║
║   🔹 ✅ HeartbeatWorker (ID: xxxxx)                              ║
╚══════════════════════════════════════════════════════════════════╝
```

## Log Markers Quick Reference

| Marker | Meaning | Type |
|--------|---------|------|
| 🚀 | Startup/Launch | State |
| ✅ | Success/OK | Status |
| ❌ | Error/Failed | Status |
| ⚠️ | Warning/Unexpected | Status |
| 🔒 | Keep-Alive/Locked | State |
| 🧵 | Thread-related | Thread |
| 💓 | Heartbeat/Health | Health |
| 🔹 | Daemon Thread | Thread |
| 🔸 | Non-Daemon Thread | Thread |
| 🔄 | Status Check | Monitoring |
| ⏱️ | Time/Duration | Timing |

## Thread Status Symbols

| Symbol | Meaning |
|--------|---------|
| 🔹 ✅ | Daemon thread, alive |
| 🔹 ❌ | Daemon thread, dead (rare) |
| 🔸 ✅ | Non-daemon thread, alive |
| 🔸 ❌ | Non-daemon thread, dead |

## Box Drawing Characters

| Type | Characters |
|------|-----------|
| Lifecycle Banners | ╔ ═ ╗ ║ ╠ ╣ ╚ ╝ |
| Exit Point Markers | ┏ ━ ┓ ┃ ┣ ┫ ┗ ┛ |

## How to Interpret Logs

### Normal Startup Sequence
1. `╔═══ 🚀 NIJA TRADING BOT STARTUP ═══╗` - Process started
2. `✅ Signal handlers registered` - Safety handlers active
3. `✅ Health check manager initialized` - Health system ready
4. `╔═══ ✅ BACKGROUND THREADS STARTED ═══╗` - Heartbeat thread running
5. Exchange credential checks...
6. Trading mode starts OR config error keep-alive

### Normal Operation
- HeartbeatWorker running silently (every 10s)
- Trading loops running (every 150s)
- Health checks responding (Railway checks every ~30s)
- Periodic status logs

### Normal Shutdown
1. Signal received (SIGTERM or SIGINT)
2. `┏━━━ ✅ EXIT POINT - Signal SIGTERM received ━━━┓`
3. Process exits with code 0
4. Railway does NOT restart (ON_FAILURE policy)

### Abnormal Shutdown (Error)
1. Error occurs during initialization or runtime
2. `┏━━━ ❌ EXIT POINT - <error type> ━━━┓`
3. Process exits with code 1
4. Railway restarts (up to 3 retries)

### Trading Loop Break
1. Trading loop exits (KeyboardInterrupt or failure)
2. `╔═══ ⚠️ TRADING LOOP INTERRUPTED ═══╗`
3. Keep-alive mode engages
4. `╔═══ 🔒 ENTERING KEEP-ALIVE MODE ═══╗`
5. Process continues running indefinitely
6. Railway sees healthy process, no restart

## Troubleshooting with Logs

### "Why is my bot restarting?"

Look for exit point markers:
- `┏━━━ ❌ EXIT POINT` = Error exit (code 1) → Railway restarts
- `┏━━━ ✅ EXIT POINT` = Normal exit (code 0) → Usually no restart

Check thread status in exit point:
- Missing HeartbeatWorker = Thread died before exit
- Multiple threads alive = Normal state

### "Is the heartbeat working?"

Look for:
- `✅ BACKGROUND THREADS STARTED` at startup
- `Thread is alive: True` in the banner
- `🧵 Heartbeat thread started` message
- `🧵 Heartbeat thread alive - N heartbeats sent` every 10 minutes

### "What mode is my bot in?"

Current state indicators:
- `🚀 STARTING INDEPENDENT MULTI-BROKER TRADING MODE` = Multi-broker
- `🚀 Starting single-broker trading loop` = Single-broker
- `🔒 ENTERING KEEP-ALIVE MODE` = Keep-alive (trading stopped)
- `⚠️ ENTERING CONFIG ERROR KEEP-ALIVE MODE` = Config error

### "Is my bot stuck?"

Check for:
- `💓 Keep-alive status check #N` - Should increment every 5 minutes
- Thread status reports - Should show HeartbeatWorker alive
- No new log entries = Process may have crashed (check Railway logs)

## Testing the Lifecycle

Use the provided `test_lifecycle_logging.py` to verify:
```bash
python3 test_lifecycle_logging.py
```

This will show example output for all log types without actually running the trading bot.
