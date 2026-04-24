"""
NIJA Command Center - Visual Preview

This script demonstrates what the Command Center dashboard displays
by printing a text-based representation of the UI.
"""

def print_command_center_preview():
    """Print ASCII art preview of the Command Center"""
    
    print("""
╔══════════════════════════════════════════════════════════════════════════════╗
║                                                                              ║
║                          ⚡ NIJA COMMAND CENTER                              ║
║                   Live Performance Dashboard - Real-time Metrics             ║
║                                                                              ║
╚══════════════════════════════════════════════════════════════════════════════╝

┌─────────────────────────┬─────────────────────────┬─────────────────────────┐
│  📈 EQUITY CURVE        │  🔥 RISK HEAT           │  ⭐ TRADE QUALITY       │
│                         │                         │                         │
│  Current Equity         │  Risk Level             │  Quality Score          │
│  $14,608.90             │  14  [LOW]              │  66  [D]                │
│  +$4,629.99 (+46.40%)   │  ▓▓░░░░░░░░░░░░░░░░░░  │  ▓▓▓▓▓▓▓▓▓▓▓▓▓░░░░░░░░  │
│                         │                         │                         │
│  Peak: $14,608.90       │  Max DD: -1.45%         │  Win Rate: 58.0%        │
│  24h Change: +46.40%    │  Current DD: 0.00%      │  Profit Factor: 1.74    │
└─────────────────────────┴─────────────────────────┴─────────────────────────┘

┌─────────────────────────┬─────────────────────────┬─────────────────────────┐
│  🎯 SIGNAL ACCURACY     │  💨 SLIPPAGE            │  💰 FEE IMPACT          │
│                         │                         │                         │
│  Accuracy Rate          │  Average Slippage       │  Total Fees             │
│  65.9%                  │  3.17 bps               │  $28.82                 │
│  ▓▓▓▓▓▓▓▓▓▓▓▓▓░░░░░░░░  │  $0.19 avg              │  Efficiency: 94         │
│                         │                         │                         │
│  Total: 41              │  Total Cost: $9.42      │  % of Profit: 6.30%     │
│  Successful: 27         │  Impact: 2.06%          │  Avg/Trade: $0.58       │
└─────────────────────────┴─────────────────────────┴─────────────────────────┘

┌─────────────────────────┬─────────────────────────────────────────────────────┐
│  ⚙️  STRATEGY EFFICIENCY│  🚀 CAPITAL GROWTH VELOCITY                         │
│                         │                                                     │
│  Efficiency Score       │  Annualized Growth Rate                             │
│  60                     │  +16,935.20%                                        │
│  ▓▓▓▓▓▓▓▓▓▓▓▓░░░░░░░░░░ │  Daily: +46.40%                                     │
│                         │                                                     │
│  Trades/Day: 50.0       │  Daily Rate: +46.40%                                │
│  Capital Use: 3.9%      │  Monthly Rate: +1,391.93%                           │
└─────────────────────────┴─────────────────────────────────────────────────────┘

╔══════════════════════════════════════════════════════════════════════════════╗
║  📊 EQUITY CURVE (24h)                                                       ║
║                                                                              ║
║  $15k ┤                                                              ╭──     ║
║       │                                                         ╭────╯       ║
║  $14k ┤                                                    ╭────╯            ║
║       │                                               ╭────╯                 ║
║  $13k ┤                                          ╭────╯                      ║
║       │                                     ╭────╯                           ║
║  $12k ┤                                ╭────╯                                ║
║       │                           ╭────╯                                     ║
║  $11k ┤                      ╭────╯                                          ║
║       │                 ╭────╯                                               ║
║  $10k ┤────────────╭────╯                                                    ║
║       └────┬────┬────┬────┬────┬────┬────┬────┬────┬────┬────┬────┬────┬─  ║
║          00:00  04:00  08:00  12:00  16:00  20:00  24:00                    ║
╚══════════════════════════════════════════════════════════════════════════════╝

                        Auto-refresh: ON | Last update: 12:34:56 PM
    """)


def print_metrics_legend():
    """Print legend explaining the metrics"""
    
    print("""
╔══════════════════════════════════════════════════════════════════════════════╗
║                           METRIC DEFINITIONS                                 ║
╚══════════════════════════════════════════════════════════════════════════════╝

📈 EQUITY CURVE
   Shows your portfolio value over time. Tracks current equity, peak equity,
   and 24-hour changes. The chart visualizes growth trajectory.

🔥 RISK HEAT (0-100 scale)
   Measures overall portfolio risk exposure. Considers drawdown, position
   concentration, and recent losses. 
   - LOW (0-25): Safe trading conditions
   - MODERATE (25-50): Normal risk levels
   - HIGH (50-75): Elevated risk, caution advised
   - CRITICAL (75-100): Dangerous levels, reduce exposure

⭐ TRADE QUALITY SCORE (0-100, graded A+ to F)
   Evaluates the quality of your trading decisions based on win rate,
   profit factor, and win/loss ratio. Higher scores indicate better
   decision-making and execution.

🎯 SIGNAL ACCURACY (0-100%)
   Measures how accurate your trading signals are. Tracks total signals,
   successful signals, and false positive rate. Higher is better.

💨 SLIPPAGE (in basis points and USD)
   Tracks the cost of execution slippage - the difference between expected
   and actual fill prices. Lower slippage indicates better execution quality.

💰 FEE IMPACT
   Measures the impact of trading fees on profitability. Shows total fees,
   fees as percentage of profit, and average fee per trade. Fee efficiency
   score rewards low fee impact (higher is better).

⚙️  STRATEGY EFFICIENCY (0-100 scale)
   Evaluates how efficiently your strategy uses capital and generates trades.
   Considers trading frequency, win rate, and capital utilization.

🚀 CAPITAL GROWTH VELOCITY (annualized %)
   Measures the rate at which your capital is growing. Shows daily, monthly,
   and annualized growth rates. Positive values indicate profitable trading.

╔══════════════════════════════════════════════════════════════════════════════╗
║                              COLOR CODING                                    ║
╚══════════════════════════════════════════════════════════════════════════════╝

GREEN  (🟢) - Positive values, good performance, low risk
RED    (🔴) - Negative values, losses, costs
YELLOW (🟡) - Neutral values, moderate levels
BLUE   (🔵) - Informational values

Progress bars fill from left to right showing metric levels.
    """)


if __name__ == "__main__":
    print_command_center_preview()
    print_metrics_legend()
