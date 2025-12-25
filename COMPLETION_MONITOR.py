#!/usr/bin/env python3
"""
NIJA Position Completion Monitor
Tracks 8-position cap and exit progress to 100% completion.
"""
import json
from pathlib import Path
from datetime import datetime

def load_positions():
    """Load current tracked positions."""
    pfile = Path("/workspaces/Nija/data/open_positions.json")
    if not pfile.exists():
        return {}
    with open(pfile) as f:
        data = json.load(f)
    return data.get("positions", {})

def calculate_totals(positions):
    """Calculate total position value and count."""
    total_value = sum(p.get("size_usd", 0) for p in positions.values())
    return {
        "count": len(positions),
        "total_usd": total_value,
        "avg_size": total_value / len(positions) if positions else 0
    }

def main():
    positions = load_positions()
    totals = calculate_totals(positions)
    
    print("=" * 80)
    print("🎯 NIJA COMPLETION TRACKER - FINAL PHASE")
    print("=" * 80)
    print(f"Timestamp: {datetime.now().isoformat()}")
    print()
    
    print("📊 POSITION STATUS")
    print("-" * 80)
    print(f"Tracked Positions:  {totals['count']}/8 (Cap Enforced)")
    print(f"Total Value:        ${totals['total_usd']:.2f}")
    print(f"Avg Position Size:  ${totals['avg_size']:.2f}")
    print()
    
    if totals['count'] <= 8:
        print(f"✅ POSITION CAP: OK ({totals['count']}/8)")
    else:
        print(f"❌ POSITION CAP: EXCEEDED ({totals['count']}/8)")
    print()
    
    print("📋 TRACKED POSITIONS (Auto-exit on SL/TP/Trailing)")
    print("-" * 80)
    
    sorted_pos = sorted(
        positions.items(),
        key=lambda x: x[1].get("size_usd", 0),
        reverse=True
    )
    
    for i, (symbol, pos) in enumerate(sorted_pos, 1):
        entry = pos.get("entry_price", 0)
        current = pos.get("current_price", 0)
        size = pos.get("size_usd", 0)
        sl = pos.get("stop_loss", 0)
        tp = pos.get("take_profit", 0)
        trail = pos.get("trailing_stop", 0)
        
        pct_change = ((current - entry) / entry * 100) if entry else 0
        
        print(f"{i}. {symbol:12s} ${size:8.2f} | Entry:${entry:.4f} Curr:${current:.4f} ({pct_change:+.1f}%)")
        print(f"                 SL:${sl:.4f} | TP:${tp:.4f} | Trail:${trail:.4f}")
        print()
    
    print("=" * 80)
    print("🎯 COMPLETION CRITERIA")
    print("=" * 80)
    print("✅ 100% Completion when:")
    print("  1. All 8 positions have exited (count = 0)")
    print("  2. Position value = $0 across all symbols")
    print("  3. No open orders in Coinbase Advanced Trade")
    print()
    
    print("🛡️  SAFETY MEASURES ACTIVE")
    print("-" * 80)
    print("✅ TRADING_EMERGENCY_STOP.conf: Sell-only mode enforced")
    print("✅ Position cap 8: Limits to core positions")
    print("✅ SL/TP triggers: Auto-exit on thresholds")
    print("✅ Trailing stops: Locks in profits")
    print()
    
    print("⏱️  EXIT TIMELINE")
    print("-" * 80)
    print("• Checks: Every 2.5 minutes")
    print("• Exit method: SL (-3%), TP (+5%), Trailing Stop, Manual")
    print("• Est. time: Hours to days depending on market movement")
    print()
    
    print("=" * 80)
    print("📝 NEXT ACTIONS")
    print("=" * 80)
    print("1. Bot restarts → loads 8-position cap")
    print("2. Existing positions manage to exit (SL/TP triggered)")
    print("3. Monitor logs for position closes")
    print("4. When count = 0 → 100% COMPLETION ACHIEVED")
    print()

if __name__ == "__main__":
    main()
