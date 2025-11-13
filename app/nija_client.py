*** Begin Patch
*** Update File: app/nija_client.py
@@
-        if os.getenv("DEBUG_JWT") == "1":
-            # Small safe preview - DO NOT SHARE publicly
-            try:
-                preview = token[:200] + "..." if token else "<no-token>"
-            except Exception:
-                preview = "<token-preview-failed>"
-            logger.info("DEBUG_JWT: token_preview=%s", preview)
-            logger.info("DEBUG_JWT: requesting URL: %s", url)
+        if os.getenv("DEBUG_JWT") == "1":
+            # Small safe preview - DO NOT SHARE publicly
+            try:
+                preview = token[:200] + "..." if token else "<no-token>"
+            except Exception:
+                preview = "<token-preview-failed>"
+            # redact the middle of the preview for safety when logging
+            try:
+                redacted_preview = (
+                    preview[:30] + "..." + preview[-30:]
+                    if preview and len(preview) > 80
+                    else preview
+                )
+            except Exception:
+                redacted_preview = "<preview-redact-failed>"
+            logger.info(f"DEBUG_JWT: token_preview={redacted_preview}")
+            logger.info(f"DEBUG_JWT: requesting URL={url}")
@@
-        if os.getenv("DEBUG_JWT") == "1":
-            try:
-                # Only log a slice to avoid huge dumps; do not expose logs publicly.
-                logger.info("DEBUG_JWT: HTTP %s response_text(500)=%s", resp.status_code, resp.text[:500])
-            except Exception:
-                logger.exception("DEBUG_JWT: could not read/print response")
+        if os.getenv("DEBUG_JWT") == "1":
+            try:
+                # Only log a slice to avoid huge dumps; do not expose logs publicly.
+                logger.info(f"DEBUG_JWT: HTTP {resp.status_code} response_text(500)={resp.text[:500]}")
+            except Exception:
+                logger.exception("DEBUG_JWT: could not read/print response")
*** End Patch
