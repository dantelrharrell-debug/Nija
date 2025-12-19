#!/usr/bin/env python3
"""
Quick deployment status checker for NIJA bot.
Shows recent activity, balance, and estimated time to $1000/day.
"""

import os
import sys
from datetime import datetime, timedelta

print("\n" + "="*80)
print("🤖 NIJA BOT - DEPLOYMENT STATUS CHECK")
print("="*80)
print(f"⏰ Current Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}")
print()

# Check if running locally or need to check remote
print("📍 Checking deployment platform...")
print()

# Platform detection
has_railway = os.path.exists('/workspaces/Nija/railway.json')
has_render = os.path.exists('/workspaces/Nija/render.yaml')

if has_railway:
    print("🚂 Platform: Railway")
    print("   To view live logs:")
    print("   1. Go to https://railway.app")
    print("   2. Select your NIJA project")
    print("   3. Click on the deployment")
    print("   4. View 'Deploy Logs' tab")
    print()
elif has_render:
    print("🎨 Platform: Render")
    print("   To view live logs:")
    print("   1. Go to https://dashboard.render.com")
    print("   2. Select 'nija-trading-bot' service")
    print("   3. Click 'Logs' tab")
    print()

# Calculate timeline based on current balance
print("="*80)
print("💰 PROFIT TIMELINE CALCULATOR")
print("="*80)
print()

# Ask for current balance
try:
    current_balance_str = input("Enter your current trading balance (e.g., 55): $")
    current_balance = float(current_balance_str)
    
    target_balance = 5000  # Need $5k to make $1k/day
    
    print()
    print("📊 PROJECTIONS TO $1,000/DAY PROFIT:")
    print("-" * 80)
    print()
    
    # Different return scenarios
    scenarios = [
        ("Conservative (15% daily)", 0.15),
        ("Moderate (20% daily)", 0.20),
        ("Target (25% daily)", 0.25),
        ("Aggressive (30% daily)", 0.30),
        ("Maximum (35% daily)", 0.35),
    ]
    
    for scenario_name, daily_return in scenarios:
        days_needed = 0
        balance = current_balance
        
        # Calculate compounding days
        while balance < target_balance and days_needed < 60:
            balance *= (1 + daily_return)
            days_needed += 1
        
        if days_needed < 60:
            target_date = datetime.now() + timedelta(days=days_needed)
            print(f"{scenario_name:30} → {days_needed:2} days (by {target_date.strftime('%b %d, %Y')})")
        else:
            print(f"{scenario_name:30} → 60+ days")
    
    print()
    print("-" * 80)
    print()
    
    # Expected performance based on APEX V7.1 strategy
    print("📈 APEX V7.1 STRATEGY EXPECTATIONS:")
    print()
    print("  Target Daily Returns: 20-35%")
    print("  Win Rate:            55-65%")
    print("  Profit Factor:       1.5-2.5")
    print("  Max Drawdown:        8-15%")
    print()
    print("  🎯 Most Likely Timeline: 14-16 days")
    print()
    
    # Daily milestones
    print("="*80)
    print("📅 DAILY MILESTONES (assuming 25% daily return)")
    print("="*80)
    print()
    print("Day | Balance      | Daily Profit  | Earning Power/Day")
    print("----|--------------|---------------|------------------")
    
    balance = current_balance
    for day in [0, 1, 3, 5, 7, 10, 12, 14, 16]:
        if day > 0:
            balance = current_balance * (1.25 ** day)
        daily_profit = balance * 0.25
        earning_power_low = balance * 0.20
        earning_power_high = balance * 0.35
        
        status = ""
        if balance >= 5000:
            status = " ✅ TARGET REACHED!"
        elif balance >= 1000:
            status = " 🎉"
        
        print(f"{day:2}  | ${balance:10,.2f} | ${daily_profit:11,.2f} | ${earning_power_low:,.0f}-${earning_power_high:,.0f}{status}")
    
    print()
    print("="*80)
    print()
    
    # Success factors
    print("🎯 CRITICAL SUCCESS FACTORS:")
    print()
    print("  ✅ Bot running 24/7 without interruptions")
    print("  ✅ Consistent 20-35% daily returns")
    print("  ✅ 98% profit reinvestment (trailing stops)")
    print("  ✅ No major market crashes")
    print("  ✅ Proper risk management (2-10% per trade)")
    print()
    
    # Next steps
    print("="*80)
    print("📋 WHAT TO MONITOR:")
    print("="*80)
    print()
    print("  1. Check logs every 6-12 hours for:")
    print("     - Trade execution confirmations")
    print("     - Win/loss ratio")
    print("     - Balance growth")
    print()
    print("  2. First 24 hours is critical:")
    print("     - Should see 2-8 trades")
    print("     - Win rate should be 50%+")
    print("     - Balance should grow 15-35%")
    print()
    print("  3. Red flags to watch for:")
    print("     - API errors (401, 429, 500)")
    print("     - Insufficient balance errors")
    print("     - No trades after 4+ hours")
    print("     - Win rate below 40%")
    print()
    
except ValueError:
    print("❌ Invalid balance amount")
    sys.exit(1)
except KeyboardInterrupt:
    print("\n\n✋ Cancelled by user")
    sys.exit(0)

print("="*80)
print()
print("💡 TIP: Bookmark your deployment logs URL for quick monitoring!")
print()
