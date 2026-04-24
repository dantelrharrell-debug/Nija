# User Position Reduction Simulation - Quick Start

## What This Does

Simulates exactly how **user_daivon_frazier**'s 59 positions and **user_tania_gilbert**'s 54 positions would reduce to 8 each during deployment, showing the expected profit/break-even outcomes.

## Quick Run

```bash
python3 simulate_user_position_reduction.py
```

## What You'll See

The simulation demonstrates:

1. **Initial State**: Total positions, capital, and P&L for each user
2. **Dust Cleanup**: Positions < $1 USD that will be closed
3. **Cap Enforcement**: Additional positions closed to reach 8-position limit
4. **Final State**: The 8 remaining positions for each user
5. **Profit/Loss Tracking**: Categorization of all closed positions as WIN, LOSS, or BREAKEVEN
6. **Combined Impact**: Overall statistics for both users

## Example Output

```
🔍 SIMULATING CLEANUP FOR: user_daivon_frazier

📊 INITIAL STATE:
   Total Positions: 59
   Total Capital: $544.08
   Total P&L: $-9.35 (-1.72%)

🧹 STEP 1: DUST CLEANUP (threshold: $1.00)
   Found 46 dust positions
   Dust Capital: $25.79
   Dust P&L: $-1.00
   Outcomes: 9 WINS, 30 LOSSES, 7 BREAKEVEN

🔒 STEP 2: POSITION CAP ENFORCEMENT (max: 8)
   Positions after dust cleanup: 13
   Over cap by: 5 positions
   Cap Excess Capital: $18.99
   Cap Excess P&L: $-0.35
   Outcomes: 1 WINS, 2 LOSSES, 2 BREAKEVEN

📊 FINAL SUMMARY FOR user_daivon_frazier
   Initial:   59 positions
   Closed:    51 positions (46 dust + 5 cap excess)
   Final:     8 positions
   Reduction: 51 positions (86.4%)
   Final Capital: $499.31 (91.8% retained)
```

## Key Results

### user_daivon_frazier
- **59 → 8 positions** (86.4% reduction)
- **91.8% of capital retained** despite closing most positions
- **51 positions closed**: 10 wins, 32 losses, 9 breakeven

### user_tania_gilbert
- **54 → 8 positions** (85.2% reduction)
- **80.6% of capital retained**
- **46 positions closed**: 22 wins, 19 losses, 5 breakeven

### Combined Impact
- **113 → 16 total positions** (85.8% reduction)
- **86.4% of total capital retained**
- **97 positions closed**: 32 wins, 51 losses, 14 breakeven

## Why This Matters

This simulation proves that the deployment will:

✅ Successfully enforce the 8-position cap  
✅ Preserve the vast majority of capital (86.4%)  
✅ Close mostly dust positions and small losing positions  
✅ Keep the largest and most valuable positions  
✅ Track all profit/loss outcomes accurately  

## Full Documentation

See [USER_POSITION_REDUCTION_SIMULATION.md](USER_POSITION_REDUCTION_SIMULATION.md) for:
- Detailed methodology
- Position-by-position breakdowns
- Capital analysis
- Implementation strategy
- Technical details

## Related Files

- **simulate_user_position_reduction.py**: The simulation script
- **bot/forced_position_cleanup.py**: Core cleanup engine
- **bot/position_cap_enforcer.py**: Position cap enforcement logic
- **FORCED_CLEANUP_GUIDE.md**: Operational guide for cleanup system
