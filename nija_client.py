class CoinbaseClient:
    # existing init, get_usd_spot_balance, etc.

    def place_order(self, symbol: str, side: str, risk_factor: float = 1.0):
        """Place a live trade on Coinbase based on account equity and risk factor."""
        try:
            balance = self.get_usd_spot_balance()
            trade_size = self.calculate_position_size(balance, risk_factor)
            if trade_size <= 0:
                raise ValueError("Trade size calculated as 0, aborting trade.")

            payload = {
                "type": "market",
                "side": side,
                "product_id": symbol,
                "funds": f"{trade_size:.2f}"  # USD amount to trade
            }
            response = self._send_request("/orders", method="POST", payload=payload)
            logging.info(f"✅ Order placed: {side.upper()} {symbol} for ${trade_size:.2f}")
            return response
        except Exception as e:
            logging.error(f"❌ Failed to place order: {e}")
            return None
