"""
NIJA Backtesting Utility
Runs TradingStrategy logic on historical data using PaperTradingAccount.
"""
import pandas as pd
import os
from datetime import datetime
from bot.trading_strategy import TradingStrategy
from bot.paper_trading import get_paper_account


def run_backtest(client, pairs, historical_data, strategy_kwargs=None):
    """
    Run backtest for given pairs and historical data.
    historical_data: dict of {pair: DataFrame}
    """
    strategy_kwargs = strategy_kwargs or {}
    paper_account = get_paper_account(initial_balance=10000.0)
    strategy = TradingStrategy(client, pairs=pairs, paper_mode=True, **strategy_kwargs)

    for pair in pairs:
        df = historical_data[pair]
        for i in range(50, len(df)):
            # Simulate a rolling window
            window = df.iloc[:i].copy()
            strategy.run_trading_cycle_for_backtest(pair, window)

    paper_account.print_summary()
    return paper_account.get_stats()

# Example usage (pseudo):
# from bot.exchange_client import ExchangeClient
# client = ExchangeClient(...)
# historical_data = {pair: pd.read_csv(f"data/{pair}_1h.csv") for pair in pairs}
# run_backtest(client, pairs, historical_data)
