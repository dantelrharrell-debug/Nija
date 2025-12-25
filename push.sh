#!/bin/bash
git config user.email "dantelrharrell@users.noreply.github.com"
git config user.name "dantelrharrell-debug"
git config commit.gpgsign false
git add bot.py bot/trading_strategy.py bot/nija_apex_strategy_v71.py bot/broker_manager.py
git commit -m "Fix API rate limiting and volume filters - scan 15s->30s, add caching, retry logic, lower thresholds"
git push origin main
