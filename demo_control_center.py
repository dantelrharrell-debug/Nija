#!/usr/bin/env python3
"""
NIJA Control Center - Demo and Testing Script

This script demonstrates the Control Center functionality without requiring
a full NIJA installation or database.

Usage:
    python demo_control_center.py
"""

import os
import sys
from pathlib import Path

# Add current directory to path
sys.path.insert(0, str(Path(__file__).parent))

print("=" * 80)
print("NIJA Control Center - Demo Script".center(80))
print("=" * 80)
print()

# Test 1: CLI Help
print("✅ Test 1: CLI Help Output")
print("-" * 80)
os.system("python nija_control_center.py --help 2>/dev/null | head -20")
print()

# Test 2: CLI Snapshot (no database required)
print("✅ Test 2: CLI Snapshot Mode (No Database)")
print("-" * 80)
os.system("python nija_control_center.py --snapshot 2>/dev/null")
print()

# Test 3: Verify API syntax
print("✅ Test 3: Control Center API Syntax")
print("-" * 80)
try:
    import ast
    with open('control_center_api.py', 'r') as f:
        ast.parse(f.read())
    print("✓ control_center_api.py syntax is valid")
except SyntaxError as e:
    print(f"✗ Syntax error in control_center_api.py: {e}")
print()

# Test 4: Check files created
print("✅ Test 4: Files Created")
print("-" * 80)
files = [
    'nija_control_center.py',
    'control_center_api.py',
    'bot/templates/control_center.html',
    'CONTROL_CENTER.md'
]

for file in files:
    if os.path.exists(file):
        size = os.path.getsize(file)
        print(f"✓ {file} ({size:,} bytes)")
    else:
        print(f"✗ {file} NOT FOUND")
print()

# Test 5: Check API endpoints
print("✅ Test 5: API Endpoint Documentation")
print("-" * 80)
print("The Control Center API provides the following endpoints:")
print()
print("Overview & Health:")
print("  GET  /api/control-center/overview")
print("  GET  /api/control-center/health")
print()
print("Users & Positions:")
print("  GET  /api/control-center/users")
print("  GET  /api/control-center/positions")
print("  GET  /api/control-center/trades/recent")
print()
print("Alerts:")
print("  GET  /api/control-center/alerts")
print("  POST /api/control-center/alerts")
print("  POST /api/control-center/alerts/{id}/acknowledge")
print("  POST /api/control-center/alerts/clear")
print()
print("Actions:")
print("  POST /api/control-center/actions/emergency-stop")
print("  POST /api/control-center/actions/pause-trading")
print("  POST /api/control-center/actions/resume-trading")
print()
print("Metrics:")
print("  GET  /api/control-center/metrics")
print()

# Test 6: Dashboard Info
print("✅ Test 6: Web Dashboard Information")
print("-" * 80)
print("To start the web dashboard:")
print()
print("  python bot/dashboard_server.py")
print()
print("Then access:")
print("  • Control Center: http://localhost:5001/control-center")
print("  • Main Dashboard: http://localhost:5001")
print("  • Users Dashboard: http://localhost:5001/users")
print()

# Summary
print("=" * 80)
print("Demo Complete!".center(80))
print("=" * 80)
print()
print("📚 For full documentation, see: CONTROL_CENTER.md")
print()
print("🚀 Quick Start Commands:")
print("  • CLI Dashboard:  python nija_control_center.py")
print("  • Web Dashboard:  python bot/dashboard_server.py")
print("  • CLI Snapshot:   python nija_control_center.py --snapshot")
print()
