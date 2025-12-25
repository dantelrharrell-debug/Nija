#!/usr/bin/env python3
import subprocess
import sys

# Change to the repo directory
import os
os.chdir('/workspaces/Nija')

# Run git commands
print("Adding changes...")
result = subprocess.run(['git', 'add', '-A'], capture_output=True, text=True)
print(result.stdout, result.stderr)

print("\nCommitting changes...")
result = subprocess.run([
    'git', 'commit', '-m', 
    'Fix: Auto-close excess positions above 8-limit (sell worst performers for profit)'
], capture_output=True, text=True)
print(result.stdout, result.stderr)

print("\nPushing to GitHub...")
result = subprocess.run(['git', 'push'], capture_output=True, text=True)
print(result.stdout, result.stderr)

if result.returncode == 0:
    print("\n✅ Changes pushed successfully! Railway will redeploy.")
else:
    print(f"\n❌ Push failed with code {result.returncode}")
    sys.exit(1)
