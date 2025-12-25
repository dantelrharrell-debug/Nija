#!/usr/bin/env python3
"""
Direct bot runner - bypasses shell script complexities
Simply loads positions and starts the trading strategy
"""

import os
import sys
import json
from pathlib import Path

# Add bot to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))

# Check prerequisites
print("\n" + "="*80)
print("🚀 NIJA BOT STARTUP")
print("="*80 + "\n")

# Check .env
if not Path(".env").exists():
    print("❌ .env file not found")
    sys.exit(1)
print("✅ .env loaded")

# Check position file
pos_file = Path("data/open_positions.json")
if not pos_file.exists():
    print("❌ Position file not found")
    sys.exit(1)

try:
    with open(pos_file) as f:
        data = json.load(f)
    pos_count = len(data.get("positions", {}))
    print(f"✅ Loaded {pos_count} positions for management")
except Exception as e:
    print(f"❌ Error loading positions: {e}")
    sys.exit(1)

print("\n" + "="*80)
print("Starting NIJA with position management...")
print("="*80 + "\n")

# EMERGENCY STOP CHECK
if os.path.exists('EMERGENCY_STOP'):
    print("\n" + "="*80)
    print("🚨 EMERGENCY STOP ACTIVE")
    print("="*80)
    print("Bot is disabled. See EMERGENCY_STOP file for details.")
    print("Delete EMERGENCY_STOP file to resume trading.")
    print("="*80 + "\n")
    sys.exit(0)

# Load environment and run the main bot
from dotenv import load_dotenv
load_dotenv()

try:
    # Import bot module and run main
    sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
    import bot as bot_module

    # Run the main bot
    bot_module.main()

except ImportError as e:
    print(f"❌ Import error: {e}")
    print("\nMake sure you're in the right directory with the venv activated")
    sys.exit(1)
except Exception as e:
    print(f"❌ Error: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
