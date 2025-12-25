#!/bin/bash
echo "🔧 Restoring apex_config.py and reapplying fix..."

# Restore original file
git checkout HEAD -- bot/apex_config.py

echo "✅ File restored from git"
