#!/usr/bin/env python3
"""
NIJA Bot Launcher - Position Management Active
Simply runs the bot to manage your 9 positions
"""

import subprocess
import sys
import os
from pathlib import Path

def load_env_file():
    """Manually load .env file since python-dotenv may not be installed"""
    env_file = Path(".env")
    if not env_file.exists():
        return False
    
    with open(env_file) as f:
        content = f.read()
    
    # Parse env vars, handling multi-line values
    lines = content.split('\n')
    current_key = None
    current_value = []
    
    for line in lines:
        line = line.rstrip()
        
        # Skip empty lines and comments when not in multi-line value
        if not current_key and (not line or line.startswith('#')):
            continue
        
        # Start of a new variable
        if '=' in line and not current_key:
            key, value = line.split('=', 1)
            key = key.strip()
            value = value.strip()
            
            # Check if value starts with quote (multi-line value)
            if value.startswith('"'):
                if value.endswith('"') and len(value) > 1:
                    # Single line quoted value
                    os.environ[key] = value[1:-1]
                else:
                    # Start of multi-line value
                    current_key = key
                    current_value = [value[1:]]  # Remove opening quote
            else:
                os.environ[key] = value
        elif current_key:
            # Continuing multi-line value
            if line.endswith('"'):
                # End of multi-line value
                current_value.append(line[:-1])  # Remove closing quote
                # Join with actual newlines
                os.environ[current_key] = '\n'.join(current_value)
                current_key = None
                current_value = []
            else:
                current_value.append(line)
    
    return True

def main():
    print("\n" + "="*80)
    print("🚀 NIJA BOT LAUNCHER")
    print("="*80 + "\n")
    
    # Check requirements
    checks = []
    
    if Path(".env").exists():
        print("✅ .env file found")
        if load_env_file():
            print("✅ Environment variables loaded")
        checks.append(True)
    else:
        print("❌ .env file not found")
        checks.append(False)
    
    if Path("data/open_positions.json").exists():
        print("✅ Position file found")
        checks.append(True)
    else:
        print("❌ Position file not found")
        checks.append(False)
    
    if not all(checks):
        print("\n❌ Cannot start bot - missing files")
        return 1
    
    print("\n" + "="*80)
    print("🤖 Starting NIJA with position management active...")
    print("="*80 + "\n")
    
    try:
        # Run bot.py from root directory
        result = subprocess.run([sys.executable, "bot.py"], check=False)
        return result.returncode
    except Exception as e:
        print(f"❌ Error: {e}")
        return 1

if __name__ == '__main__':
    sys.exit(main())
