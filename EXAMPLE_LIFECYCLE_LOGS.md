# NIJA Lifecycle - Example Log Output

This document shows what you'll see in the actual logs when NIJA runs with the new visual verification features.

## Example 1: Normal Startup and Trading

```
2026-02-06 21:58:30 - nija - INFO - 
2026-02-06 21:58:30 - nija - INFO - ╔══════════════════════════════════════════════════════════════════════════════╗
2026-02-06 21:58:30 - nija - INFO - ║                        🚀 NIJA TRADING BOT STARTUP                           ║
2026-02-06 21:58:30 - nija - INFO - ╠══════════════════════════════════════════════════════════════════════════════╣
2026-02-06 21:58:30 - nija - INFO - ║ Process ID: 42                                                               ║
2026-02-06 21:58:30 - nija - INFO - ║ Python Version: 3.11.7                                                       ║
2026-02-06 21:58:30 - nija - INFO - ║ Working Directory: /app                                                      ║
2026-02-06 21:58:30 - nija - INFO - ║ Initializing lifecycle management...                                        ║
2026-02-06 21:58:30 - nija - INFO - ╚══════════════════════════════════════════════════════════════════════════════╝
2026-02-06 21:58:30 - nija - INFO - 
2026-02-06 21:58:30 - nija - INFO - ✅ Signal handlers registered (SIGTERM, SIGINT)
2026-02-06 21:58:30 - nija - INFO - ✅ Health check manager initialized
2026-02-06 21:58:30 - nija - INFO - 🧵 Heartbeat thread started (ID: 139876543210, Interval: 10s)
2026-02-06 21:58:30 - nija - INFO - 
2026-02-06 21:58:30 - nija - INFO - ╔══════════════════════════════════════════════════════════════════════════════╗
2026-02-06 21:58:30 - nija - INFO - ║                      ✅ BACKGROUND THREADS STARTED                            ║
2026-02-06 21:58:30 - nija - INFO - ╠══════════════════════════════════════════════════════════════════════════════╣
2026-02-06 21:58:30 - nija - INFO - ║ HeartbeatWorker: Thread ID 139876543210                                      ║
2026-02-06 21:58:30 - nija - INFO - ║ Update Interval: 10 seconds                                                  ║
2026-02-06 21:58:30 - nija - INFO - ║ Thread is alive: True                                                        ║
2026-02-06 21:58:30 - nija - INFO - ║ Health checks will be responsive to Railway (~30s check interval)            ║
2026-02-06 21:58:30 - nija - INFO - ╚══════════════════════════════════════════════════════════════════════════════╝
2026-02-06 21:58:30 - nija - INFO - 

... (credential validation logs) ...

2026-02-06 21:58:32 - nija - INFO - 🌐 Health server listening on port 5000
2026-02-06 21:58:32 - nija - INFO -    📍 Liveness:  http://0.0.0.0:5000/health
2026-02-06 21:58:32 - nija - INFO -    📍 Readiness: http://0.0.0.0:5000/ready
2026-02-06 21:58:32 - nija - INFO -    📍 Status:    http://0.0.0.0:5000/status
2026-02-06 21:58:32 - nija - INFO -    📍 Metrics:   http://0.0.0.0:5000/metrics

... (trading strategy initialization) ...

2026-02-06 21:58:35 - nija - INFO - 🚀 Starting single-broker trading loop (2.5 minute cadence)...
2026-02-06 21:58:35 - nija - INFO - 🔁 Main trading loop iteration #1
2026-02-06 22:01:05 - nija - INFO - 🔁 Main trading loop iteration #2
2026-02-06 22:03:35 - nija - INFO - 🔁 Main trading loop iteration #3
```

## Example 2: Trading Loop Interrupted, Entering Keep-Alive

```
2026-02-06 22:06:05 - nija - INFO - 🔁 Main trading loop iteration #4
2026-02-06 22:08:12 - nija - INFO - 
2026-02-06 22:08:12 - nija - INFO - ╔══════════════════════════════════════════════════════════════════════════════╗
2026-02-06 22:08:12 - nija - INFO - ║              ⚠️  TRADING LOOP INTERRUPTED - Single-Broker Mode                ║
2026-02-06 22:08:12 - nija - INFO - ╠══════════════════════════════════════════════════════════════════════════════╣
2026-02-06 22:08:12 - nija - INFO - ║ KeyboardInterrupt received in single-broker trading loop                    ║
2026-02-06 22:08:12 - nija - INFO - ║ Completed 4 trading cycles                                                   ║
2026-02-06 22:08:12 - nija - INFO - ║ Exiting trading loop...                                                      ║
2026-02-06 22:08:12 - nija - INFO - ║ Total Threads: 3                                                             ║
2026-02-06 22:08:12 - nija - INFO - ║   🔸 ✅ MainThread (ID: 139876543100)                                         ║
2026-02-06 22:08:12 - nija - INFO - ║   🔹 ✅ HeartbeatWorker (ID: 139876543210)                                    ║
2026-02-06 22:08:12 - nija - INFO - ║   🔹 ✅ HealthServer (ID: 139876543220)                                       ║
2026-02-06 22:08:12 - nija - INFO - ╚══════════════════════════════════════════════════════════════════════════════╝
2026-02-06 22:08:12 - nija - INFO - 
2026-02-06 22:08:12 - nija - INFO - 
2026-02-06 22:08:12 - nija - INFO - ╔══════════════════════════════════════════════════════════════════════════════╗
2026-02-06 22:08:12 - nija - INFO - ║                        🔒 ENTERING KEEP-ALIVE MODE                           ║
2026-02-06 22:08:12 - nija - INFO - ╠══════════════════════════════════════════════════════════════════════════════╣
2026-02-06 22:08:12 - nija - INFO - ║ Trading loops have exited, but process will remain alive                    ║
2026-02-06 22:08:12 - nija - INFO - ║ This prevents Railway from restarting the service                           ║
2026-02-06 22:08:12 - nija - INFO - ║ Heartbeat maintained by heartbeat_worker background thread (10s)            ║
2026-02-06 22:08:12 - nija - INFO - ║ Status logging every 300s                                                    ║
2026-02-06 22:08:12 - nija - INFO - ║ To shutdown: Use SIGTERM or SIGINT (handled by signal handlers)             ║
2026-02-06 22:08:12 - nija - INFO - ║ Total Threads: 3                                                             ║
2026-02-06 22:08:12 - nija - INFO - ║   🔸 ✅ MainThread (ID: 139876543100)                                         ║
2026-02-06 22:08:12 - nija - INFO - ║   🔹 ✅ HeartbeatWorker (ID: 139876543210)                                    ║
2026-02-06 22:08:12 - nija - INFO - ║   🔹 ✅ HealthServer (ID: 139876543220)                                       ║
2026-02-06 22:08:12 - nija - INFO - ╚══════════════════════════════════════════════════════════════════════════════╝
2026-02-06 22:08:12 - nija - INFO - 
2026-02-06 22:13:12 - nija - INFO - 💓 Keep-alive status check #1 (heartbeat via background thread)
2026-02-06 22:18:12 - nija - INFO - 💓 Keep-alive status check #2 (heartbeat via background thread)
2026-02-06 22:23:12 - nija - INFO - 💓 Keep-alive status check #3 (heartbeat via background thread)
...
2026-02-06 23:08:12 - nija - INFO - 💓 Keep-alive status check #12 (heartbeat via background thread)
2026-02-06 23:08:12 - nija - INFO - 🧵 Thread Status Report:
2026-02-06 23:08:12 - nija - INFO -    Total Threads: 3
2026-02-06 23:08:12 - nija - INFO -      🔸 ✅ MainThread (ID: 139876543100)
2026-02-06 23:08:12 - nija - INFO -      🔹 ✅ HeartbeatWorker (ID: 139876543210)
2026-02-06 23:08:12 - nija - INFO -      🔹 ✅ HealthServer (ID: 139876543220)
```

## Example 3: Configuration Error - No Credentials

```
2026-02-06 21:58:30 - nija - INFO - 
2026-02-06 21:58:30 - nija - INFO - ╔══════════════════════════════════════════════════════════════════════════════╗
2026-02-06 21:58:30 - nija - INFO - ║                        🚀 NIJA TRADING BOT STARTUP                           ║
2026-02-06 21:58:30 - nija - INFO - ╠══════════════════════════════════════════════════════════════════════════════╣
2026-02-06 21:58:30 - nija - INFO - ║ Process ID: 42                                                               ║
2026-02-06 21:58:30 - nija - INFO - ║ Python Version: 3.11.7                                                       ║
2026-02-06 21:58:30 - nija - INFO - ║ Working Directory: /app                                                      ║
2026-02-06 21:58:30 - nija - INFO - ║ Initializing lifecycle management...                                        ║
2026-02-06 21:58:30 - nija - INFO - ╚══════════════════════════════════════════════════════════════════════════════╝
2026-02-06 21:58:30 - nija - INFO - 

... (background threads start) ...

2026-02-06 21:58:31 - nija.broker_integration - ERROR - ═══════════════════════════════════════════════════════════════════
2026-02-06 21:58:31 - nija.broker_integration - ERROR - ❌ CRITICAL: NO EXCHANGE CREDENTIALS CONFIGURED
2026-02-06 21:58:31 - nija.broker_integration - ERROR - ═══════════════════════════════════════════════════════════════════
2026-02-06 21:58:31 - nija.broker_integration - ERROR - The bot cannot trade without exchange API credentials.
2026-02-06 21:58:31 - nija.broker_integration - INFO - Starting health server to report configuration status...
2026-02-06 21:58:31 - nija - INFO - 🌐 Health server listening on port 5000
2026-02-06 21:58:31 - nija - INFO - 
2026-02-06 21:58:31 - nija - INFO - ╔══════════════════════════════════════════════════════════════════════════════╗
2026-02-06 21:58:31 - nija - INFO - ║              ⚠️  ENTERING CONFIG ERROR KEEP-ALIVE MODE                        ║
2026-02-06 21:58:31 - nija - INFO - ╠══════════════════════════════════════════════════════════════════════════════╣
2026-02-06 21:58:31 - nija - INFO - ║ No exchange credentials configured - cannot trade                           ║
2026-02-06 21:58:31 - nija - INFO - ║ Process will stay alive for health monitoring                               ║
2026-02-06 21:58:31 - nija - INFO - ║ Container will NOT restart automatically                                    ║
2026-02-06 21:58:31 - nija - INFO - ║ Heartbeat interval: 60s                                                      ║
2026-02-06 21:58:31 - nija - INFO - ║ Configure credentials and manually restart deployment                       ║
2026-02-06 21:58:31 - nija - INFO - ║ Total Threads: 2                                                             ║
2026-02-06 21:58:31 - nija - INFO - ║   🔸 ✅ MainThread (ID: 139876543100)                                         ║
2026-02-06 21:58:31 - nija - INFO - ║   🔹 ✅ HeartbeatWorker (ID: 139876543210)                                    ║
2026-02-06 21:58:31 - nija - INFO - ╚══════════════════════════════════════════════════════════════════════════════╝
2026-02-06 21:58:31 - nija - INFO - 
2026-02-06 22:08:31 - nija - INFO - ⏱️  Config error keep-alive: 600s elapsed
2026-02-06 22:18:31 - nija - INFO - ⏱️  Config error keep-alive: 1200s elapsed
```

## Example 4: Graceful Shutdown (SIGTERM)

```
2026-02-06 22:23:45 - nija - INFO - 💓 Keep-alive status check #3 (heartbeat via background thread)
2026-02-06 22:24:10 - nija - INFO - 
2026-02-06 22:24:10 - nija - INFO - ┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
2026-02-06 22:24:10 - nija - INFO - ┃ ✅ EXIT POINT - Signal SIGTERM received                                              ┃
2026-02-06 22:24:10 - nija - INFO - ┃ Exit Code:                                                                 0 ┃
2026-02-06 22:24:10 - nija - INFO - ┃ PID:                                                                      42 ┃
2026-02-06 22:24:10 - nija - INFO - ┣━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┫
2026-02-06 22:24:10 - nija - INFO - ┃ Graceful shutdown initiated by signal handler                               ┃
2026-02-06 22:24:10 - nija - INFO - ┃ This is an expected exit (not a crash)                                      ┃
2026-02-06 22:24:10 - nija - INFO - ┃ Total Threads: 3                                                             ┃
2026-02-06 22:24:10 - nija - INFO - ┃   🔸 ✅ MainThread (ID: 139876543100)                                         ┃
2026-02-06 22:24:10 - nija - INFO - ┃   🔹 ✅ HeartbeatWorker (ID: 139876543210)                                    ┃
2026-02-06 22:24:10 - nija - INFO - ┃   🔹 ✅ HealthServer (ID: 139876543220)                                       ┃
2026-02-06 22:24:10 - nija - INFO - ┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛
2026-02-06 22:24:10 - nija - INFO - 
```

## Example 5: Fatal Error - Broker Connection Failed

```
2026-02-06 21:58:35 - nija - ERROR - Failed to initialize Coinbase broker
2026-02-06 21:58:35 - nija - INFO - 
2026-02-06 21:58:35 - nija - INFO - ┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
2026-02-06 21:58:35 - nija - INFO - ┃ ❌ EXIT POINT - Broker Connection Failed                                            ┃
2026-02-06 21:58:35 - nija - INFO - ┃ Exit Code:                                                                 1 ┃
2026-02-06 21:58:35 - nija - INFO - ┃ PID:                                                                      42 ┃
2026-02-06 21:58:35 - nija - INFO - ┣━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┫
2026-02-06 21:58:35 - nija - INFO - ┃ RuntimeError: Broker connection failed                                      ┃
2026-02-06 21:58:35 - nija - INFO - ┃ Coinbase credentials not found or invalid                                   ┃
2026-02-06 21:58:35 - nija - INFO - ┃                                                                              ┃
2026-02-06 21:58:35 - nija - INFO - ┃ Check and set ONE of:                                                        ┃
2026-02-06 21:58:35 - nija - INFO - ┃ 1. PEM File: COINBASE_PEM_PATH=/path/to/file.pem                             ┃
2026-02-06 21:58:35 - nija - INFO - ┃ 2. PEM Content: COINBASE_PEM_CONTENT='-----BEGIN...'                         ┃
2026-02-06 21:58:35 - nija - INFO - ┃ 3. Base64 PEM: COINBASE_PEM_BASE64='<base64>'                                ┃
2026-02-06 21:58:35 - nija - INFO - ┃ 4. API Key+Secret: COINBASE_API_KEY & COINBASE_API_SECRET                    ┃
2026-02-06 21:58:35 - nija - INFO - ┃                                                                              ┃
2026-02-06 21:58:35 - nija - INFO - ┃ Total Threads: 2                                                             ┃
2026-02-06 21:58:35 - nija - INFO - ┃   🔸 ✅ MainThread (ID: 139876543100)                                         ┃
2026-02-06 21:58:35 - nija - INFO - ┃   🔹 ✅ HeartbeatWorker (ID: 139876543210)                                    ┃
2026-02-06 21:58:35 - nija - INFO - ┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛
2026-02-06 21:58:35 - nija - INFO - 
2026-02-06 21:58:35 - nija - ERROR - Fatal error initializing bot: Broker connection failed
... (Railway will restart the service) ...
```

## Example 6: Emergency Stop File Detected

```
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ 🚨 EXIT POINT - EMERGENCY STOP FILE DETECTED                             ┃
┃ Exit Code: 0                                                             ┃
┃ PID:                                                                   42 ┃
┣━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┫
┃ Bot is disabled. See EMERGENCY_STOP file for details.                   ┃
┃ Delete EMERGENCY_STOP file to resume trading.                           ┃
┃ This is an intentional shutdown (not a crash).                          ┃
┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛
```

## Key Observations

### What Makes a "Good" Log

1. **Clear Entry Points**
   - `╔═══ 🚀 NIJA TRADING BOT STARTUP ═══╗` marks the beginning
   - Shows PID, Python version, working directory
   - Easy to find in log files

2. **Thread Visibility**
   - Thread IDs shown in all important places
   - Daemon status clear (🔹 vs 🔸)
   - Alive status always visible (✅ vs ❌)

3. **State Transitions**
   - Big banners (╔═══╗) for major state changes
   - Previous and new state both clear
   - Thread count always shown

4. **Exit Points**
   - Different box style (┏━━━┓) from lifecycle banners
   - Exit code prominently displayed
   - Reason for exit in title
   - Thread status at exit time

5. **Periodic Updates**
   - Keep-alive heartbeat every 5 minutes
   - Thread status report every hour
   - Helps verify process is alive

### What to Look For

**Process is healthy:**
- Regular `💓 Keep-alive status check #N` logs (every 5 min)
- No exit point markers
- Heartbeat thread alive in status reports

**Process crashed:**
- `┏━━━ ❌ EXIT POINT` marker appears
- Exit Code: 1
- Check error details in the marker box

**Graceful shutdown:**
- `┏━━━ ✅ EXIT POINT` marker
- Exit Code: 0
- "Signal SIGTERM/SIGINT received"

**Something's stuck:**
- No new logs for > 10 minutes
- Check Railway for process status
- May need manual restart

## Railway-Specific Behavior

### With These Logs, You Can See:

1. **Why Railway restarted:**
   - Look for last `┏━━━` exit point before restart
   - Exit Code 0 = Shouldn't restart (check Railway config)
   - Exit Code 1 = Expected restart (fix the error)

2. **Whether heartbeat is working:**
   - `✅ BACKGROUND THREADS STARTED` at startup
   - Regular `💓 Keep-alive` messages
   - Thread status shows HeartbeatWorker alive

3. **What state the bot is in:**
   - Trading: `🚀 STARTING ... TRADING MODE`
   - Keep-alive: `🔒 ENTERING KEEP-ALIVE MODE`
   - Config error: `⚠️ ENTERING CONFIG ERROR KEEP-ALIVE MODE`

4. **How long it's been running:**
   - Keep-alive counter: `#1, #2, #3...` = 5 min each
   - Config error elapsed time: Shown every 10 minutes

5. **Thread health:**
   - Hourly reports in keep-alive mode
   - Exit point markers always show threads
   - Can spot dead threads immediately
