# trading_logic.py
import pandas as pd
from indicators import compute_vwap, compute_rsi
from data_fetcher import get_historic_candles_symbol

# Rules:
# - If close > VWAP and RSI between 40-70 -> consider Long readiness
# - If close < VWAP and RSI between 30-60 -> consider Short readiness
# - If RSI > 70 -> overbought -> consider close longs / short bias
# - If RSI < 30 -> oversold -> consider close shorts / long bias
# Output signal dict: {"signal": "LONG"/"SHORT"/"HOLD", "reason": str, "rsi":float, "vwap":float, "price":float}

def generate_signal(symbol, client=None, granularity_seconds=60, lookback=100, rsi_period=14):
    df = get_historic_candles_symbol(symbol, granularity_seconds=granularity_seconds, limit=lookback, client=client)
    # ensure numeric types
    df[['open','high','low','close','volume']] = df[['open','high','low','close','volume']].apply(pd.to_numeric, errors='coerce').fillna(method='ffill')
    # compute indicators
    vwap_series = compute_vwap(df)
    rsi_series = compute_rsi(df['close'], period=rsi_period)
    latest = df.iloc[-1]
    latest_vwap = float(vwap_series.iloc[-1])
    latest_rsi = float(rsi_series.iloc[-1])
    price = float(latest['close'])

    # Basic decision rules
    reason = []
    if price > latest_vwap and 40 <= latest_rsi <= 70:
        signal = "LONG"
        reason.append("price > VWAP & RSI neutral-high")
    elif price < latest_vwap and 30 <= latest_rsi <= 60:
        signal = "SHORT"
        reason.append("price < VWAP & RSI neutral-low")
    elif latest_rsi > 70:
        # overbought -> favor short or exit longs
        signal = "SHORT"
        reason.append("RSI > 70 (overbought)")
    elif latest_rsi < 30:
        signal = "LONG"
        reason.append("RSI < 30 (oversold)")
    else:
        signal = "HOLD"
        reason.append("no clear condition")

    return {
        "symbol": symbol,
        "signal": signal,
        "reason": "; ".join(reason),
        "rsi": round(latest_rsi, 2),
        "vwap": round(latest_vwap, 2),
        "price": round(price, 2)
    }
