"""
NIJA Parameter Optimization Script

This script runs a grid search over key strategy parameters using historical data and logs the best results.
Update DATA_PATH, PAIRS, and parameter ranges as needed.
"""
import pandas as pd
import os
from bot.backtest import run_backtest
from itertools import product

# === CONFIGURATION ===
DATA_PATH = "data"
PAIRS = ["BTC-USD", "ETH-USD"]
CSV_SUFFIX = "_1h.csv"

# Parameter grid (edit as needed)
BASE_ALLOCATIONS = [5.0, 10.0, 15.0]  # % of balance per trade
MAX_EXPOSURES = [0.5, 0.7, 0.85]      # max % of account in positions
SIGNAL_THRESHOLDS = [2, 3, 4]         # min signal score for entry
STOP_LOSS_PCTS = [0.01, 0.02, 0.03]   # base stop loss percent

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
best_result = None
best_params = None
results = []

for base_allocation, max_exposure, min_signal, stop_loss in product(BASE_ALLOCATIONS, MAX_EXPOSURES, SIGNAL_THRESHOLDS, STOP_LOSS_PCTS):
    print(f"\nTesting: base_allocation={base_allocation}, max_exposure={max_exposure}, min_signal={min_signal}, stop_loss={stop_loss}")
    strategy_kwargs = {
        'base_allocation': base_allocation,
        'max_exposure': max_exposure,
        # You may need to wire min_signal and stop_loss into your TradingStrategy logic
    }
    stats = run_backtest(client, list(historical_data.keys()), historical_data, strategy_kwargs)
    result = {
        'base_allocation': base_allocation,
        'max_exposure': max_exposure,
        'min_signal': min_signal,
        'stop_loss': stop_loss,
        **stats
    }
    results.append(result)
    # Use final_balance as main metric (customize as needed)
    if best_result is None or stats.get('final_balance', 0) > best_result.get('final_balance', 0):
        best_result = stats
        best_params = result

print("\n=== Best Parameter Set ===")
print(best_params)

print("\n=== All Results ===")
for r in results:
    print(r)
