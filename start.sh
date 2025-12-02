#!/usr/bin/env bash
set -euo pipefail

echo "=============================="
echo "   STARTING NIJA TRADING BOT  "
echo "=============================="
echo "LIVE_TRADING=${LIVE_TRADING:-0}"
echo

###########################################
# WRITE PEM FILE IF JWT PEM IS PROVIDED
###########################################
if [ -n "${COINBASE_JWT_PEM:-}" ]; then
  echo "[INFO] COINBASE_JWT_PEM detected — writing to /tmp/coinbase.pem"
  printf "%s\n" "$COINBASE_JWT_PEM" > /tmp/coinbase.pem
  chmod 600 /tmp/coinbase.pem
  export COINBASE_PEM_PATH="/tmp/coinbase.pem"
  echo "[INFO] PEM written and COINBASE_PEM_PATH exported"
else
  echo "[INFO] No COINBASE_JWT_PEM provided — skipping PEM write"
fi

echo
echo "[INFO] Running preflight checks..."

# Check python
python3 --version || python --version

# Check that bot folder exists
if [ ! -d "./bot" ]; then
  echo "[ERROR] ./bot folder not found!"
  exit 1
fi

# Check entrypoint
if [ ! -f "./bot/live_trading.py" ] && [ ! -f "./start_bot.sh" ]; then
  echo "[ERROR] No bot entrypoint found!"
  echo "Expected: ./bot/live_trading.py OR ./start_bot.sh"
  exit 1
fi

echo "[INFO] Preflight OK"
echo

###########################################
# START THE BOT
###########################################
echo "Launching NIJA bot..."

if [ -f "./bot/live_trading.py" ]; then
  echo "[INFO] Running python ./bot/live_trading.py"
  exec python ./bot/live_trading.py
elif [ -f "./start_bot.sh" ]; then
  echo "[INFO] Running ./start_bot.sh"
  exec ./start_bot.sh
fi

###########################################
# SAFETY FALLBACK (should never hit)
###########################################
echo "[ERROR] No valid start command found!"
exit 1
