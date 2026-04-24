"""
bot.capital — Capital aggregation layer for NIJA Trading Bot.

Single source of truth for all capital figures consumed by the trading
pipeline.  External callers should obtain the singleton via::

    from bot.capital.active_capital import get_active_capital

    capital = get_active_capital()
    balance = capital.get_total_available_balance()
"""
