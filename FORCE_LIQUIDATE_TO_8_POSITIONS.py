#!/usr/bin/env python3
"""
Force liquidate excess positions to reach 8-position cap.
Keeps the 8 largest positions, sells the 6 smallest.
"""
import json
import os
from pathlib import Path

# Load current positions
positions_file = Path("/workspaces/Nija/data/open_positions.json")
if not positions_file.exists():
    print("❌ No positions file found")
    exit(1)

with open(positions_file) as f:
    data = json.load(f)

positions = data.get("positions", {})
print(f"📊 Currently tracking {len(positions)} positions")
print()

# Calculate position values
position_values = []
for symbol, pos in positions.items():
    value = pos.get("size_usd", 0)
    position_values.append((symbol, value, pos))

# Sort by value descending
position_values.sort(key=lambda x: x[1], reverse=True)

# Keep top 8, mark rest for liquidation
keep = position_values[:8]
liquidate = position_values[8:]

print("=" * 70)
print("🛡️  POSITIONS TO KEEP (TOP 8 BY VALUE)")
print("=" * 70)
for i, (symbol, value, pos) in enumerate(keep, 1):
    print(f"{i:2d}. {symbol:12s} ${value:10.2f}")

print()
print("=" * 70)
print("🔴 POSITIONS TO LIQUIDATE (EXCESS)")
print("=" * 70)
for i, (symbol, value, pos) in enumerate(liquidate, 1):
    print(f"{i:2d}. {symbol:12s} ${value:10.2f}")

print()
print("=" * 70)
print("📝 LIQUIDATION PLAN")
print("=" * 70)
print(f"Remove {len(liquidate)} positions to reach cap of 8")
print()

# Create modified positions file with only the top 8
new_positions = {}
for symbol, _, pos in keep:
    new_positions[symbol] = pos

# Update open_positions.json
data["positions"] = new_positions
with open(positions_file, 'w') as f:
    json.dump(data, f, indent=2)

print(f"✅ Updated open_positions.json to keep only {len(new_positions)} positions")

# Create FORCE_EXIT_EXCESS.conf to trigger liquidation
force_exit_file = Path("/workspaces/Nija/FORCE_EXIT_EXCESS.conf")
force_exit_file.write_text("")
print(f"✅ Created {force_exit_file.name} to trigger forced exits")

print()
print("=" * 70)
print("🚀 ACTION REQUIRED")
print("=" * 70)
print("Positions file updated. On next bot restart:")
print("  1. Bot will attempt to exit liquidation positions")
print("  2. Existing positions will trigger natural exits (SL/TP)")
print("  3. Final count: 8 positions managed to completion")
print()
