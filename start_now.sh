#!/bin/bash
# Remove emergency stop and start bot
rm -f /workspaces/Nija/EMERGENCY_STOP
cd /workspaces/Nija
python3 start_bot_direct.py
