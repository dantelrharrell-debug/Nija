# ✅ NIJA POSITION MANAGEMENT - READY TO START

## How to Start the Bot

Choose **one** of these commands:

### 1️⃣ Simplest (Python)
```bash
python3 run_bot.py
```

### 2️⃣ Direct Python
```bash
python3 start_bot_direct.py
```

### 3️⃣ Shell Script
```bash
bash run_bot_position_management.sh
```

All three do the same thing - they start the bot with position management enabled.

---

## What Bot Does

✅ **Loads** your 9 positions from `data/open_positions.json`  
✅ **Monitors** each position every 2.5 minutes  
✅ **Closes** positions when stops/takes hit (automatically)  
✅ **Logs** all activity to `nija.log`  
✅ **Repeats** indefinitely 24/7  

---

## What to Expect

**When it starts:**
- See "🚀 NIJA BOT LAUNCHER" 
- Confirmation of .env and position file
- Bot begins monitoring

**While running:**
- Every 2.5 minutes: price checks logged
- When price moves 2-5%: position closes logged
- Freed capital available for new trades

**In nija.log:**
```
✅ NIJA BOT LAUNCHER
✅ .env file found
✅ Position file found

🤖 Starting NIJA with position management active...

(Bot runs continuously, monitoring your 9 positions)
```

---

## Stop Bot Anytime

Press `Ctrl+C` in the terminal where bot is running.

Position data is saved - safe to restart anytime.

---

## Ready?

```bash
python3 run_bot.py
```

**Status**: ✅ **READY TO RUN**  
**Action**: Start the bot  
**Timeline**: First exits expected days 3-5
