#!/bin/bash
# Restart bot with circuit breaker fix
cd /workspaces/Nija
pkill -f "python.*bot.py"
sleep 2
nohup python3 bot.py > nija_output.log 2>&1 &
echo "Bot restarted with circuit breaker fix"
