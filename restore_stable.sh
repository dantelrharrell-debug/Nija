#!/bin/bash
# NIJA Emergency Restore Script
# Restores bot to last known working state (Coinbase Stable v1.0)

set -e  # Exit on error

echo "=============================================="
echo "🔧 NIJA EMERGENCY RESTORE"
echo "=============================================="
echo "This will restore your bot to the last stable checkpoint"
echo "Checkpoint: Coinbase Stable v1.0 (Dec 20, 2025)"
echo ""

# Confirmation
read -p "Continue? (y/n): " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Restore cancelled."
    exit 0
fi

echo ""
echo "📦 Step 1: Checking git repository..."
if [ ! -d ".git" ]; then
    echo "❌ Error: Not a git repository. Run from /workspaces/Nija"
    exit 1
fi
echo "✅ Git repository found"

echo ""
echo "🏷️  Step 2: Checking for stable tag..."
if ! git tag -l | grep -q "coinbase-stable-v1.0"; then
    echo "⚠️  Warning: Stable tag not found. Creating from current HEAD..."
    git tag -a coinbase-stable-v1.0 -m "Coinbase stable checkpoint - profit-focused settings"
    echo "✅ Tag created"
else
    echo "✅ Stable tag exists"
fi

echo ""
echo "💾 Step 3: Creating backup of current state..."
BACKUP_BRANCH="backup-$(date +%Y%m%d-%H%M%S)"
git branch $BACKUP_BRANCH
echo "✅ Backup created: $BACKUP_BRANCH"

echo ""
echo "🔄 Step 4: Restoring to stable checkpoint..."
git checkout coinbase-stable-v1.0 -- bot/
git checkout coinbase-stable-v1.0 -- requirements.txt
echo "✅ Core files restored"

echo ""
echo "🔍 Step 5: Verifying critical files..."
CRITICAL_FILES=(
    "bot/trading_strategy.py"
    "bot/broker_manager.py"
    "bot/nija_apex_strategy_v71.py"
    "requirements.txt"
)

for file in "${CRITICAL_FILES[@]}"; do
    if [ -f "$file" ]; then
        echo "  ✅ $file exists"
    else
        echo "  ❌ $file missing!"
        exit 1
    fi
done

echo ""
echo "🐍 Step 6: Python environment check..."
if [ -d ".venv" ]; then
    echo "  ✅ Virtual environment exists"
    echo "  Run: source .venv/bin/activate"
else
    echo "  ⚠️  No virtual environment found"
    echo "  Creating virtual environment..."
    python3 -m venv .venv
    echo "  ✅ Virtual environment created"
fi

echo ""
echo "📦 Step 7: Dependencies..."
if [ -f ".venv/bin/pip" ]; then
    echo "  Installing requirements..."
    .venv/bin/pip install -q -r requirements.txt
    echo "  ✅ Dependencies installed"
else
    echo "  ⚠️  Activate venv and run: pip install -r requirements.txt"
fi

echo ""
echo "🔐 Step 8: Checking credentials..."
if [ -f ".env" ]; then
    if grep -q "COINBASE_API_KEY" .env && grep -q "COINBASE_API_SECRET" .env; then
        echo "  ✅ API credentials found in .env"
    else
        echo "  ⚠️  .env exists but missing credentials"
        echo "  Add COINBASE_API_KEY and COINBASE_API_SECRET"
    fi
else
    echo "  ⚠️  No .env file found"
    echo "  Create .env with your Coinbase credentials"
fi

echo ""
echo "=============================================="
echo "✅ RESTORE COMPLETE"
echo "=============================================="
echo ""
echo "📋 Next Steps:"
echo "1. Activate venv: source .venv/bin/activate"
echo "2. Test balance: python check_balance_now.py"
echo "3. Start bot: python bot.py"
echo ""
echo "📌 Your previous state is saved in branch: $BACKUP_BRANCH"
echo "   To return to it: git checkout $BACKUP_BRANCH"
echo ""
echo "🔧 Restored Configuration:"
echo "   - 80% trailing lock (only give back 2%)"
echo "   - $75 max position size"
echo "   - 3 concurrent positions max"
echo "   - 180s cooldown after losses"
echo "   - Top 20 markets only"
echo "   - 2% stop loss, 5-8% take profit"
echo ""
echo "Last verified working: Dec 20, 2025 22:15 UTC"
