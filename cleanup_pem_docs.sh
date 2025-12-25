#!/bin/bash
# Remove outdated PEM-focused documentation

cd /workspaces/Nija

echo "🗑️  Removing PEM-related documentation files..."

rm -f COINBASE_CONNECTION_FIX.md
rm -f scripts/test_coinbase_connection.py
rm -f test_connection.sh
rm -f commit_coinbase_fix.sh
rm -f quick_commit.sh

echo "✅ Cleanup complete"

ls -la *.md scripts/test*.py scripts/*connection*.sh 2>/dev/null || echo "(No matching files found - already clean)"
