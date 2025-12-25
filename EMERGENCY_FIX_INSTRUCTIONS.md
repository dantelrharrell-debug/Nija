# Emergency Fix Instructions

## The Problem
Bot shows "0 positions" but actually has 8 positions worth $1.54M.
Result: NO exits are being checked, all capital is locked.

## The Solution
Run the emergency fix script to:
1. Stop the broken bot
2. Sync all 8 positions from Coinbase  
3. Restart with position tracking working

## Quick Fix (Run in Terminal)

```bash
chmod +x emergency_fix.sh && ./emergency_fix.sh
```

## Manual Fix (If script fails)

### Step 1: Stop the bot
```bash
pkill -f bot.py
```

### Step 2: Sync positions
```bash
python3 emergency_sync_positions.py
```

### Step 3: Check the file
```bash
cat data/open_positions.json | grep -c "symbol"
```
Should show 8 positions.

### Step 4: Restart
```bash
bash start.sh
```

## After Restart

Monitor the logs to confirm positions loaded:
```bash
tail -f nija.log | grep -E "💾 Found|✅ Loaded|Managing|positions"
```

You should see:
- "💾 Found 8 saved positions from previous session"
- "✅ Loaded 8 positions from file"  
- "📊 Managing 8 open position(s)..."

## If Startup Fails

Check what went wrong:
```bash
tail -50 nija.log
```

Common issues:
- Missing .env credentials
- Python packages not installed: `pip install -r requirements.txt`
- Port already in use: change PORT in .env

## Verify It's Fixed

After 30 seconds, check if exits are working:
```bash
tail -20 nija.log | grep "Managing"
```

Should see position management running every cycle.
