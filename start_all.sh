#!/bin/bash
set -e

# Start bot and web (bot background, web foreground)
/app/bot/start_bot.sh &
sleep 1
exec /app/web/start_web.sh
