#!/bin/bash
# Remove emergency liquidation trigger files
cd /workspaces/Nija || exit 1
rm -f LIQUIDATE_ALL_NOW.conf
rm -f FORCE_LIQUIDATE_ALL_NOW.conf
rm -f FORCE_EXIT_ALL.conf
rm -f FORCE_EXIT_EXCESS.conf
rm -f FORCE_EXIT_OVERRIDE.conf
echo "✅ Emergency triggers removed"
ls -la *.conf 2>/dev/null || echo "No .conf files remaining"
