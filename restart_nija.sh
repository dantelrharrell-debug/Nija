#!/bin/bash
set -e

echo "=============================="
echo "  RESTARTING NIJA TRADING BOT"
echo "=============================="

# Find the bot.py process and send SIGTERM (match only bot.py specifically)
BOT_PID=$(pgrep -f "python[0-9.]*.*[/]bot\.py" || echo "")

if [ -z "$BOT_PID" ]; then
    echo "❌ NIJA bot process not found"
    echo "   The bot may not be running"
    exit 1
fi

echo "Found NIJA bot process: PID $BOT_PID"
echo "Sending SIGTERM signal for graceful shutdown..."

kill -TERM "$BOT_PID"

echo "✅ Restart signal sent"
echo "   The deployment platform will automatically restart the bot"
echo ""
echo "To check if the bot restarted successfully:"
echo "  tail -f nija.log"
echo ""
