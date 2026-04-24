"""
NIJA Parameter Optimization Script

This script runs a grid search over key strategy parameters using historical data and logs the best results.
"""
import pandas as pd
import os
import itertools
from bot.backtest import run_backtest

# === CONFIGURATION ===
DATA_PATH = "data"  # Folder with CSVs like BTC-USD_1h.csv, ETH-USD_1h.csv, etc.
PAIRS = ["BTC-USD", "ETH-USD"]  # Add more pairs as needed
CSV_SUFFIX = "_1h.csv"  # Change to match your data files

# Parameter grid (edit as needed)
base_allocations = [5.0, 10.0, 15.0]  # % of balance per trade
max_exposures = [0.5, 0.7, 0.85]      # max % of account in positions
max_daily_losses = [0.01, 0.025, 0.05] # max daily loss %
pyramidings = [True, False]

# === LOAD HISTORICAL DATA ===
historical_data = {}
for pair in PAIRS:
    csv_file = os.path.join(DATA_PATH, f"{pair}{CSV_SUFFIX}")
    if not os.path.exists(csv_file):
        print(f"Missing data file: {csv_file}")
        continue
    df = pd.read_csv(csv_file)
    historical_data[pair] = df

if not historical_data:
    print("No historical data loaded. Please add CSVs to the data/ folder.")
    exit(1)

# === DUMMY CLIENT (for backtest, not used) ===
class DummyClient:
    def get_accounts(self):
        return {"accounts": []}
    def get_product(self, product_id):
        return {"price": 1.0}

client = DummyClient()

# === GRID SEARCH ===
results = []
param_grid = list(itertools.product(base_allocations, max_exposures, max_daily_losses, pyramidings))
print(f"Testing {len(param_grid)} parameter combinations...")

for base_allocation, max_exposure, max_daily_loss, pyramiding in param_grid:
    print(f"\nParams: base_allocation={base_allocation}, max_exposure={max_exposure}, max_daily_loss={max_daily_loss}, pyramiding={pyramiding}")
    stats = run_backtest(
        client,
        list(historical_data.keys()),
        historical_data,
        strategy_kwargs={
            'base_allocation': base_allocation,
            'max_exposure': max_exposure,
            'max_daily_loss': max_daily_loss,
            'pyramiding_enabled': pyramiding
        }
    )
    result = {
        'base_allocation': base_allocation,
        'max_exposure': max_exposure,
        'max_daily_loss': max_daily_loss,
        'pyramiding_enabled': pyramiding,
        **stats
    }
    results.append(result)

# === SORT AND PRINT BEST RESULTS ===
results = sorted(results, key=lambda x: (-x.get('final_balance', 0), x.get('max_drawdown', 1)))
print("\n=== Top 5 Parameter Sets ===")
for r in results[:5]:
    print(r)

# Optionally, save all results to CSV
pd.DataFrame(results).to_csv("optimization_results.csv", index=False)
print("\nAll results saved to optimization_results.csv")
