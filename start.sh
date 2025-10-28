#!/usr/bin/env bash
# -------------------------------
# start.sh for Nija bot
# -------------------------------

# Exit on any error
set -e

echo "🌟 Starting Nija bot..."

# Activate virtual environment
if [ -f ".venv/bin/activate" ]; then
    source .venv/bin/activate
    echo "✅ Virtualenv activated."
else
    echo "⚠️ Virtualenv not found. Make sure you installed dependencies."
fi

# Optional: upgrade pip
pip install --upgrade pip

# Install requirements just in case
pip install -r requirements.txt

# Export environment variables (if not already set in Render dashboard)
# export COINBASE_API_KEY="your_api_key"
# export COINBASE_API_SECRET="your_api_secret"
# export COINBASE_API_PASSPHRASE="your_passphrase"
# export API_PEM_B64="your_base64_pem_string"

# Run the Nija bot in the background with logging
nohup python3 nija_live_snapshot.py > nija_bot.log 2>&1 &

# Print status
echo "✅ Nija bot started in background."
echo "📄 Logs are being written to nija_bot.log"
