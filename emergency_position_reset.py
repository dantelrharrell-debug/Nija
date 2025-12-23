#!/usr/bin/env python3
"""
EMERGENCY: Reset position tracking to match actual Coinbase holdings
"""
import json
import os
from datetime import datetime

# Clear the corrupted position file
positions_file = "data/open_positions.json"

# Create minimal valid structure
reset_data = {
    "timestamp": datetime.utcnow().isoformat(),
    "positions": {}
}

# Backup the old file first
if os.path.exists(positions_file):
    backup_file = f"data/open_positions_backup_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.json"
    os.rename(positions_file, backup_file)
    print(f"📦 Backed up old positions to: {backup_file}")

# Write clean slate
with open(positions_file, 'w') as f:
    json.dump(reset_data, f, indent=2)

print("✅ Position tracking file reset")
print("🔄 Bot will resync from Coinbase on next startup")
