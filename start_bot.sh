#!/bin/bash
# Correct path inside container
if [ -f /app/bot/bot.py ]; then
    echo "Found bot.py, starting..."
    python3 /app/bot/bot.py
else
    echo "Error: /app/bot/bot.py not found"
    ls -l /app/bot
    exit 1
fi
