#!/usr/bin/env python3
"""Execute cleanup by running bash script"""
import subprocess
import sys

result = subprocess.run(
    ["bash", "/workspaces/Nija/do_cleanup.sh"],
    cwd="/workspaces/Nija",
    capture_output=True,
    text=True
)

print(result.stdout)
if result.stderr:
    print("STDERR:", result.stderr, file=sys.stderr)
    
sys.exit(result.returncode)
