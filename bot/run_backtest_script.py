"""
NIJA Backtest Runner Script

This script loads historical data, runs the NIJA backtest, and prints results.
Update the DATA_PATH and PAIRS as needed.
"""
import pandas as pd
import os
from bot.backtest import run_backtest

# === CONFIGURATION ===
DATA_PATH = "data"  # Folder with CSVs like BTC-USD_1h.csv, ETH-USD_1h.csv, etc.
PAIRS = ["BTC-USD", "ETH-USD"]  # Add more pairs as needed
CSV_SUFFIX = "_1h.csv"  # Change to match your data files

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

# === RUN BACKTEST ===
print("\n=== Running NIJA Backtest ===\n")
stats = run_backtest(client, list(historical_data.keys()), historical_data)

print("\n=== Backtest Results ===")
for k, v in stats.items():
    print(f"{k}: {v}")
