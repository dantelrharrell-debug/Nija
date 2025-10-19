import asyncio
import websockets
import json
from datetime import datetime
from nija_bot import TRADING_PAIRS, update_live_data, ai_signal, get_account_balance, calculate_position_size, place_order

COINBASE_WS_URL = "wss://ws-feed.exchange.coinbase.com"


async def subscribe():
    async with websockets.connect(COINBASE_WS_URL) as ws:
        subscribe_msg = {
            "type": "subscribe",
            "product_ids": TRADING_PAIRS,
            "channels": ["ticker"]
        }
        await ws.send(json.dumps(subscribe_msg))
        print("🟢 Connected to Coinbase WebSocket")

        async for message in ws:
            try:
                msg = json.loads(message)
            except Exception:
                continue

            if msg.get("type") != "ticker":
                continue

            pair = msg.get("product_id")
            # some tickers may not contain price/last_size exactly - defensive parsing
            try:
                price = float(msg.get("price", 0) or 0)
            except Exception:
                price = 0.0
            try:
                volume = float(msg.get("last_size", 0) or 0)
            except Exception:
                volume = 0.0

            timestamp = datetime.now()
            update_live_data(pair, price, volume, timestamp)

            # Generate AI decision and place trade
            decision = ai_signal(pair)
            balance = get_account_balance("USD")
            size_usd = calculate_position_size(balance)
            # If you want dynamic risk per-signal in future, change calculate_position_size call
            if decision in ("buy", "sell") and size_usd > 0:
                # WARNING: this will place live trades. Start small.
                place_order(pair, decision, size_usd)


def run_bot():
    loop = asyncio.get_event_loop()
    try:
        loop.run_until_complete(subscribe())
    except KeyboardInterrupt:
        print("Shutting down websocket bot")
    except Exception as e:
        print("Websocket loop error:", e)
    finally:
        loop.close()


if __name__ == "__main__":
    run_bot()
