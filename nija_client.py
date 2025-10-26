*** Begin Patch
*** Update File: nija_client.py
@@
 from decimal import Decimal
 import time
 import logging
+import os
+import json
+import sys
+try:
+    import requests
+except Exception:
+    requests = None
@@
 logger = logging.getLogger("nija_client")
 logger.setLevel(logging.INFO)
+# Ensure log output goes to stdout so Render / Railway capture it in "safe" logs
+if not logger.handlers:
+    sh = logging.StreamHandler(stream=sys.stdout)
+    sh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
+    logger.addHandler(sh)
+
+# Environment-driven webhook endpoints (optional)
+# Set any of these to a webhook URL you control to receive order notifications:
+# - RENDER_LOG_ENDPOINT
+# - RAILWAY_LOG_ENDPOINT
+# - GENERIC_LOG_ENDPOINT
+RENDER_LOG_ENDPOINT = os.getenv("RENDER_LOG_ENDPOINT")
+RAILWAY_LOG_ENDPOINT = os.getenv("RAILWAY_LOG_ENDPOINT")
+GENERIC_LOG_ENDPOINT = os.getenv("GENERIC_LOG_ENDPOINT")
+
@@
 class NijaClientWrapper:
@@
     def create_order_safe(self, side: str, product_id: str, size_btc: Decimal, usd_size: Decimal, price_usd: Decimal):
@@
-                if hasattr(self.client, "place_market_order"):
-                    return self.client.place_market_order(product_id=product_id, side=side, size=size_str)
+                if hasattr(self.client, "place_market_order"):
+                    resp = self.client.place_market_order(product_id=product_id, side=side, size=size_str)
+                    # notify & log
+                    try:
+                        self._on_order_success(resp, side, product_id, size_btc, usd_size, price_usd)
+                    except Exception as e:
+                        logger.debug("post-order notify failed (ignored): %s", e)
+                    return resp
@@
-                if hasattr(self.client, "create_order"):
-                    try:
-                        return self.client.create_order(product_id=product_id, side=side, order_type='market', size=size_str)
-                    except TypeError:
-                        # try positional fallback
-                        return self.client.create_order(product_id, side, 'market', size_str)
+                if hasattr(self.client, "create_order"):
+                    try:
+                        resp = self.client.create_order(product_id=product_id, side=side, order_type='market', size=size_str)
+                    except TypeError:
+                        # try positional fallback
+                        resp = self.client.create_order(product_id, side, 'market', size_str)
+                    # notify & log
+                    try:
+                        self._on_order_success(resp, side, product_id, size_btc, usd_size, price_usd)
+                    except Exception as e:
+                        logger.debug("post-order notify failed (ignored): %s", e)
+                    return resp
@@
-                if hasattr(self.client, "send_order"):
-                    return self.client.send_order(product_id=product_id, side=side, size=size_str, type='market')
-                if hasattr(self.client, "order"):
-                    return self.client.order(product_id=product_id, side=side, size=size_str, type='market')
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
@@
         logger.error("All order attempts failed. Last error: %s", last_exc)
         raise last_exc
+
+    # ----------------------------
+    # Order success handler / notifications
+    # ----------------------------
+    def _on_order_success(self, resp, side, product_id, size_btc: Decimal, usd_size: Decimal, price_usd: Decimal):
+        """
+        Called after an order is successfully placed/returned by the underlying client.
+        - Writes a structured JSON line to stdout (captured by Render/Railway).
+        - Optionally POSTs the same payload to webhook endpoints if env vars set.
+        This method must never raise in production trading (we catch exceptions where it's called).
+        """
+        # Build a safe payload (do not include API keys or secrets)
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
+
+        # 1) Structured stdout log (Render/Railway capture)
+        try:
+            logger.info("ORDER_PLACED %s", json.dumps(payload))
+        except Exception:
+            # fallback to plain print in worst case
+            try:
+                print(json.dumps(payload), file=sys.stdout)
+            except Exception:
+                pass
+
+        # 2) Optional webhook notifications (non-blocking / defensive)
+        endpoints = [RENDER_LOG_ENDPOINT, RAILWAY_LOG_ENDPOINT, GENERIC_LOG_ENDPOINT]
+        for ep in endpoints:
+            if not ep:
+                continue
+            # Send minimal POST; swallow all errors and use short timeout
+            try:
+                if requests is None:
+                    logger.debug("requests not available; skipping HTTP notify to %s", ep)
+                    continue
+                # Use a short timeout so we don't block trading loop
+                headers = {"Content-Type": "application/json"}
+                # don't include the full resp object if it's not JSON-serializable - we already summarized it
+                requests.post(ep, json=payload, headers=headers, timeout=2.0)
+            except Exception as e:
+                # log at debug level; do not raise
+                logger.debug("Webhook notify to %s failed (ignored): %s", ep, e)
+
+
+def _summarize_response(resp):
+    """
+    Produce a small, safe summary of the underlying client's response for telemetry.
+    Avoid including raw auth tokens or bulky data.
+    """
+    try:
+        if resp is None:
+            return None
+        # if dict-like, pick small keys if present
+        if isinstance(resp, dict):
+            return {k: resp.get(k) for k in ['id', 'status', 'filled_size', 'size', 'price'] if k in resp}
+        # if object with attrs, try to map similar small set
+        summary = {}
+        for k in ('id', 'status', 'filled_size', 'size', 'price'):
+            val = getattr(resp, k, None)
+            if val is not None:
+                summary[k] = val
+        if summary:
+            return summary
+        # fallback to str(resp) truncated
+        s = str(resp)
+        return s if len(s) < 400 else s[:400] + "..."
+    except Exception:
+        return None
*** End Patch
