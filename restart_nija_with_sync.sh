#!/bin/bash
# Restart NIJA with position sync enabled

echo "🔄 Restarting NIJA Bot with Position Sync..."

# Kill any running bot processes
pkill -9 -f "python3 bot.py" 2>/dev/null || true
pkill -9 -f "python bot.py" 2>/dev/null || true

sleep 2

echo "✅ Old processes killed"
echo "🚀 Starting NIJA with position sync..."

# Start fresh bot
cd /workspaces/Nija
python3 bot.py &

echo "✅ NIJA restarted - check nija.log for position sync"
echo "   tail -f nija.log | grep -E 'SYNC|position|TRACK'"
