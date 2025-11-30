#!/bin/bash
set -e

echo "=== STARTING NIJA TRADING BOT CONTAINER ==="

# Add vendored path to PYTHONPATH just in case
export PYTHONPATH="$PYTHONPATH:/app/app/cd/vendor/coinbase_advanced_py"

# Test if coinbase_advanced can be imported
python - <<END
try:
    import coinbase_advanced
    print("coinbase_advanced module installed ✅")
except ModuleNotFoundError:
    print("coinbase_advanced module NOT installed ❌. Live trading disabled")
END

# Start Gunicorn
exec gunicorn -c gunicorn.conf.py app.wsgi:app
