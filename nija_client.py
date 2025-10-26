*** Begin Patch
*** Add File: nija_client.py
+""" 
+Nija Coinbase client adapter / safe order wrapper.
+
+This file exposes `NijaClientWrapper` which adapts a variety of coinbase client method
+names into a stable interface used by NIJA strategy code:
+  - get_spot_price(product_id) -> float
+  - get_usd_balance() -> Decimal
+  - create_order_safe(side, product_id, size_btc, usd_size, price_usd) -> underlying order response
+
+It also logs structured JSON to stdout (captured by Render/Railway) and optionally POSTs
+order notifications to webhook endpoints set via env vars:
+ - RENDER_LOG_ENDPOINT
+ - RAILWAY_LOG_ENDPOINT
+ - GENERIC_LOG_ENDPOINT
+"""
+from decimal import Decimal
+import time
+import logging
+import os
+import json
+import sys
+
+try:
+    import requests
+except Exception:
+    requests = None
+
+logger = logging.getLogger("nija_client")
+logger.setLevel(logging.INFO)
+if not logger.handlers:
+    sh = logging.StreamHandler(stream=sys.stdout)
+    sh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
+    logger.addHandler(sh)
+
+RENDER_LOG_ENDPOINT = os.getenv("RENDER_LOG_ENDPOINT")
+RAILWAY_LOG_ENDPOINT = os.getenv("RAILWAY_LOG_ENDPOINT")
+GENERIC_LOG_ENDPOINT = os.getenv("GENERIC_LOG_ENDPOINT")
+
+
+class NijaClientWrapper:
+    def __init__(self, coinbase_client):
+        self.client = coinbase_client
+
+    def get_spot_price(self, product_id: str = 'BTC-USD') -> float:
+        try:
+            if hasattr(self.client, "get_spot_price"):
+                p = self.client.get_spot_price(product_id)
+                return float(p)
+        except Exception as e:
+            logger.debug("get_spot_price() direct failed: %s", e)
+        try:
+            if hasattr(self.client, "get_ticker"):
+                t = self.client.get_ticker(product_id)
+                if isinstance(t, dict) and ('price' in t or 'last' in t):
+                    return float(t.get('price') or t.get('last'))
+        except Exception as e:
+            logger.debug("get_ticker() failed: %s", e)
+        try:
+            if hasattr(self.client, "ticker"):
+                t = self.client.ticker(product_id)
+                if isinstance(t, dict) and 'price' in t:
+                    return float(t['price'])
+        except Exception as e:
+            logger.debug("ticker() failed: %s", e)
+        try:
+            if hasattr(self.client, "get_last_trade"):
+                lt = self.client.get_last_trade(product_id)
+                if isinstance(lt, dict) and 'price' in lt:
+                    return float(lt['price'])
+        except Exception as e:
+            logger.debug("get_last_trade() failed: %s", e)
+        raise RuntimeError("Failed to fetch spot price from underlying coinbase client.")
+
+    def get_usd_balance(self) -> Decimal:
+        try:
+            if hasattr(self.client, "get_account_balance"):
+                b = self.client.get_account_balance('USD')
+                return Decimal(str(b))
+        except Exception as e:
+            logger.debug("get_account_balance('USD') failed: %s", e)
+        try:
+            if hasattr(self.client, "get_accounts"):
+                accounts = self.client.get_accounts()
+                for a in accounts:
+                    cur = (a.get('currency') if isinstance(a, dict) else getattr(a, 'currency', None))
+                    if cur == 'USD':
+                        available = (a.get('available') if isinstance(a, dict) else getattr(a, 'available', None))
+                        balance = (a.get('balance') if isinstance(a, dict) else getattr(a, 'balance', None))
+                        val = available or balance or 0
+                        return Decimal(str(val))
+        except Exception as e:
+            logger.debug("get_accounts() scan failed: %s", e)
+        raise RuntimeError("Failed to retrieve USD balance from underlying coinbase client.")
+
+    def create_order_safe(self, side: str, product_id: str, size_btc: Decimal, usd_size: Decimal, price_usd: Decimal):
+        if size_btc is None or usd_size is None:
+            raise ValueError("size_btc and usd_size must be provided.")
+        if size_btc <= 0:
+            raise ValueError("Order size too small to place (size_btc <= 0).")
+        if side not in ('buy', 'sell'):
+            raise ValueError("side must be 'buy' or 'sell'.")
+        if side == 'buy':
+            usd_bal = self.get_usd_balance()
+            if usd_size > usd_bal:
+                raise ValueError(f"Insufficient USD balance: need {usd_size}, have {usd_bal}")
+        size_str = format(size_btc, 'f')
+        usd_str = format(usd_size, 'f')
+        last_exc = None
+        for attempt in range(3):
+            try:
+                logger.info("Placing order attempt %d: %s %s (btc=%s usd=%s price=%s)",
+                            attempt + 1, side, product_id, size_str, usd_str, str(price_usd))
+                if hasattr(self.client, "place_market_order"):
+                    resp = self.client.place_market_order(product_id=product_id, side=side, size=size_str)
+                    try:
+                        self._on_order_success(resp, side, product_id, size_btc, usd_size, price_usd)
+                    except Exception as e:
+                        logger.debug("post-order notify failed (ignored): %s", e)
+                    return resp
+                if hasattr(self.client, "create_order"):
+                    try:
+                        resp = self.client.create_order(product_id=product_id, side=side, order_type='market', size=size_str)
+                    except TypeError:
+                        resp = self.client.create_order(product_id, side, 'market', size_str)
+                    try:
+                        self._on_order_success(resp, side, product_id, size_btc, usd_size, price_usd)
+                    except Exception as e:
+                        logger.debug("post-order notify failed (ignored): %s", e)
+                    return resp
+                if hasattr(self.client, "send_order"):
+                    resp = self.client.send_order(product_id=product_id, side=side, size=size_str, type='market')
+                    try:
+                        self._on_order_success(resp, side, product_id, size_btc, usd_size, price_usd)
+                    except Exception as e:
+                        logger.debug("post-order notify failed (ignored): %s", e)
+                    return resp
+                if hasattr(self.client, "order"):
+                    resp = self.client.order(product_id=product_id, side=side, size=size_str, type='market')
+                    try:
+                        self._on_order_success(resp, side, product_id, size_btc, usd_size, price_usd)
+                    except Exception as e:
+                        logger.debug("post-order notify failed (ignored): %s", e)
+                    return resp
+                raise RuntimeError("No known order placement method found on coinbase client.")
+            except Exception as e:
+                last_exc = e
+                logger.warning("Order attempt %d failed: %s", attempt + 1, e)
+                time.sleep(0.4)
+        logger.error("All order attempts failed. Last error: %s", last_exc)
+        raise last_exc
+
+    def _on_order_success(self, resp, side, product_id, size_btc: Decimal, usd_size: Decimal, price_usd: Decimal):
+        payload = {
+            "event": "nija_order_placed",
+            "side": side,
+            "product_id": product_id,
+            "size_btc": str(size_btc),
+            "usd_size": str(usd_size),
+            "price_usd": str(price_usd),
+            "timestamp": int(time.time()),
+            "response_sample": _summarize_response(resp)
+        }
+        try:
+            logger.info("ORDER_PLACED %s", json.dumps(payload))
+        except Exception:
+            try:
+                print(json.dumps(payload), file=sys.stdout)
+            except Exception:
+                pass
+        endpoints = [RENDER_LOG_ENDPOINT, RAILWAY_LOG_ENDPOINT, GENERIC_LOG_ENDPOINT]
+        for ep in endpoints:
+            if not ep:
+                continue
+            try:
+                if requests is None:
+                    logger.debug("requests not available; skipping HTTP notify to %s", ep)
+                    continue
+                headers = {"Content-Type": "application/json"}
+                requests.post(ep, json=payload, headers=headers, timeout=2.0)
+            except Exception as e:
+                logger.debug("Webhook notify to %s failed (ignored): %s", ep, e)
+
+
+def _summarize_response(resp):
+    try:
+        if resp is None:
+            return None
+        if isinstance(resp, dict):
+            return {k: resp.get(k) for k in ['id', 'status', 'filled_size', 'size', 'price'] if k in resp}
+        summary = {}
+        for k in ('id', 'status', 'filled_size', 'size', 'price'):
+            val = getattr(resp, k, None)
+            if val is not None:
+                summary[k] = val
+        if summary:
+            return summary
+        s = str(resp)
+        return s if len(s) < 400 else s[:400] + "..."
+    except Exception:
+        return None
+
+
+def wrap_coinbase_client(raw_client):
+    return NijaClientWrapper(raw_client)
+
+
+if __name__ == '__main__':
+    class _Mock:
+        def __init__(self):
+            self._usd = 12.0
+            self.btc_price = 50000.0
+            self.orders = []
+        def get_spot_price(self, product_id): return float(self.btc_price)
+        def get_account_balance(self, currency): return float(self._usd) if currency == 'USD' else 0.0
+        def place_market_order(self, product_id, side, size):
+            o = {"product_id": product_id, "side": side, "size": size, "status": "filled"}
+            self.orders.append(o)
+            return o
+        def get_accounts(self): return [{"currency": "USD", "available": float(self._usd), "balance": float(self._usd)}]
+
+    mock = _Mock()
+    wrapper = NijaClientWrapper(mock)
+    price = wrapper.get_spot_price('BTC-USD')
+    bal = wrapper.get_usd_balance()
+    print("price:", price, "usd balance:", bal)
+    from decimal import Decimal
+    resp = wrapper.create_order_safe('buy', 'BTC-USD', Decimal('0.00002'), Decimal('1.00'), Decimal(str(price)))
+    print("order resp:", resp)
*** End Patch
