# Nija AI v5 Trading Bot (Auto-Start)

**WARNING: This bot places LIVE market orders. Use extreme caution and start with tiny amounts.**

## What this repo contains
- Real-time WebSocket trading bot (`nija_bot_ws.py`) — streams Coinbase ticker and trades live.
- AI trading engine (`nija_bot.py`) — VWAP + RSI signal logic, position sizing.
- Flask dashboard (`nija_bot_web.py`) — simple monitoring endpoint at `/`.
- Auto-start wrapper (`start_nija.sh`) and `Procfile` for Render/Railway.
- `requirements.txt` with pinned packages.

## Quick setup (local / Codespaces)
1. Clone your `Nija` repo and paste these files into the root.
2. Create a virtual environment (recommended):
   ```bash
   python -m venv .venv
   source .venv/bin/activate
