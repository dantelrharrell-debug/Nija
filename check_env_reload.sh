#!/bin/bash
# Force Environment Variable Reload Script
# This script helps diagnose and reload environment variables

set -e

echo "======================================================================================================"
echo "                              FORCE ENVIRONMENT VARIABLE RELOAD"
echo "======================================================================================================"
echo ""

# Step 1: Show current environment
echo "STEP 1: Current Environment Status"
echo "------------------------------------------------------------------------------------------------------"
echo ""

if [ -f .env ]; then
    echo "✅ .env file exists - will load environment variables from it"
    echo ""
    echo "   Loading .env file..."
    set -a
    . ./.env
    set +a
    echo "   ✅ .env loaded successfully"
else
    echo "⚠️  No .env file found - using system environment variables only"
    echo ""
    echo "   This is normal for Railway/Render deployments (they use platform env vars)"
fi

echo ""
echo "------------------------------------------------------------------------------------------------------"
echo "STEP 2: Diagnostic - Running Environment Variable Check"
echo "------------------------------------------------------------------------------------------------------"
echo ""

# Run the diagnostic script if it exists
if [ -f diagnose_env_vars.py ]; then
    python3 diagnose_env_vars.py
    DIAG_EXIT=$?
    echo ""
    echo "   Diagnostic script exit code: $DIAG_EXIT"
    if [ $DIAG_EXIT -eq 0 ]; then
        echo "   ✅ At least one exchange is properly configured"
    else
        echo "   ⚠️  No exchanges fully configured"
    fi
else
    echo "   ⚠️  diagnose_env_vars.py not found - skipping detailed diagnostic"
    
    # Basic check for key variables
    echo ""
    echo "   Basic credential check:"
    
    if [ -n "${KRAKEN_MASTER_API_KEY}" ] && [ -n "${KRAKEN_MASTER_API_SECRET}" ]; then
        echo "      ✅ KRAKEN Master: Configured"
    else
        echo "      ❌ KRAKEN Master: Not configured"
    fi
    
    if [ -n "${COINBASE_API_KEY}" ] && [ -n "${COINBASE_API_SECRET}" ]; then
        echo "      ✅ COINBASE: Configured"
    else
        echo "      ❌ COINBASE: Not configured"
    fi
    
    if [ -n "${ALPACA_API_KEY}" ] && [ -n "${ALPACA_API_SECRET}" ]; then
        echo "      ✅ ALPACA: Configured"
    else
        echo "      ❌ ALPACA: Not configured"
    fi
fi

echo ""
echo "------------------------------------------------------------------------------------------------------"
echo "STEP 3: Recommendations"
echo "------------------------------------------------------------------------------------------------------"
echo ""

# Count configured exchanges
CONFIGURED_COUNT=0

if [ -n "${KRAKEN_MASTER_API_KEY}" ] && [ -n "${KRAKEN_MASTER_API_SECRET}" ]; then
    CONFIGURED_COUNT=$((CONFIGURED_COUNT + 1))
fi

if [ -n "${COINBASE_API_KEY}" ] && [ -n "${COINBASE_API_SECRET}" ]; then
    CONFIGURED_COUNT=$((CONFIGURED_COUNT + 1))
fi

if [ -n "${ALPACA_API_KEY}" ] && [ -n "${ALPACA_API_SECRET}" ]; then
    CONFIGURED_COUNT=$((CONFIGURED_COUNT + 1))
fi

if [ -n "${OKX_API_KEY}" ] && [ -n "${OKX_API_SECRET}" ] && [ -n "${OKX_PASSPHRASE}" ]; then
    CONFIGURED_COUNT=$((CONFIGURED_COUNT + 1))
fi

if [ -n "${BINANCE_API_KEY}" ] && [ -n "${BINANCE_API_SECRET}" ]; then
    CONFIGURED_COUNT=$((CONFIGURED_COUNT + 1))
fi

echo "   Configured Exchanges: $CONFIGURED_COUNT"
echo ""

if [ $CONFIGURED_COUNT -eq 0 ]; then
    echo "   ❌ NO EXCHANGES CONFIGURED"
    echo ""
    echo "   You need to add API credentials to enable trading."
    echo ""
    echo "   🚂 For Railway deployment:"
    echo "      1. Go to https://railway.app → Your Project → Variables tab"
    echo "      2. Add environment variables (e.g., KRAKEN_MASTER_API_KEY)"
    echo "      3. Click 'Restart Deployment' to reload env vars"
    echo ""
    echo "   🎨 For Render deployment:"
    echo "      1. Go to https://dashboard.render.com → Your Service → Environment tab"
    echo "      2. Add environment variables"
    echo "      3. Service will auto-redeploy OR click 'Manual Deploy'"
    echo ""
    echo "   💻 For local deployment:"
    echo "      1. Copy .env.example to .env"
    echo "      2. Edit .env and add your API credentials"
    echo "      3. Run ./start.sh (this script will load .env automatically)"
    echo ""
elif [ $CONFIGURED_COUNT -lt 2 ]; then
    echo "   ⚠️  ONLY $CONFIGURED_COUNT EXCHANGE CONFIGURED"
    echo ""
    echo "   Consider adding more exchanges for:"
    echo "      • Better diversification"
    echo "      • Reduced API rate limiting"
    echo "      • More resilient trading"
    echo ""
else
    echo "   ✅ $CONFIGURED_COUNT EXCHANGES CONFIGURED"
    echo ""
    echo "   Your bot is properly configured for multi-exchange trading!"
    echo ""
fi

echo "   📖 For detailed instructions, see:"
echo "      • RESTART_DEPLOYMENT.md (how to restart Railway/Render)"
echo "      • KRAKEN_SETUP_GUIDE.md (Kraken API setup)"
echo "      • MULTI_EXCHANGE_TRADING_GUIDE.md (multi-exchange setup)"
echo ""

echo "======================================================================================================"
echo "                              ENVIRONMENT CHECK COMPLETE"
echo "======================================================================================================"
echo ""

if [ $CONFIGURED_COUNT -gt 0 ]; then
    echo "✅ You can now run the bot with: ./start.sh"
    exit 0
else
    echo "⚠️  Please configure at least one exchange before running the bot"
    echo "   See recommendations above for next steps"
    exit 1
fi
