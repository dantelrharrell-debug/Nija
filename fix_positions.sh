#!/bin/bash
echo "Discarding corrupted apex_config.py changes..."
cd /workspaces/Nija
git checkout -- bot/apex_config.py
echo "✅ File restored"
echo ""
echo "Now applying proper fix to set max_positions=8..."
python3 << 'EOF'
import re

# Read the file
with open('bot/apex_config.py', 'r') as f:
    content = f.read()

# Replace max_positions 5 -> 8 (two occurrences)
content = re.sub(
    r"'max_positions':\s*5,\s*#\s*Maximum concurrent positions",
    "'max_positions': 8,  # Maximum concurrent positions (matches trading_strategy.py limit)",
    content
)

# Write back
with open('bot/apex_config.py', 'w') as f:
    f.write(content)

print("✅ Fixed max_positions: 5 → 8")
print("   Updated all occurrences in apex_config.py")
EOF

echo ""
echo "Verifying changes..."
grep -n "max_positions" bot/apex_config.py
