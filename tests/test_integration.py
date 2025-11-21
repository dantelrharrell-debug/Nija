"""
test_integration.py - Integration tests for the complete safe trading stack.

This test verifies:
- MODE environment variable behavior
- Configuration loading
- Safe order submission flow
- TradingView webhook integration
- Audit logging
"""

import os
import sys
import json
import tempfile
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Set test environment
temp_dir = tempfile.mkdtemp()
os.environ["MODE"] = "DRY_RUN"
os.environ["LOG_PATH"] = f"{temp_dir}/orders.log"
os.environ["MAX_ORDER_USD"] = "100"
os.environ["MAX_ORDERS_PER_MINUTE"] = "5"
os.environ["MANUAL_APPROVAL_COUNT"] = "0"
os.environ["TRADINGVIEW_WEBHOOK_SECRET"] = "test_secret"

print("=" * 60)
print("INTEGRATION TEST: Safe Trading Stack")
print("=" * 60)

# Test 1: Config loading
print("\n[1/7] Testing configuration loading...")
import config
assert config.MODE == "DRY_RUN"
assert config.MAX_ORDER_USD == 100.0
assert config.MAX_ORDERS_PER_MINUTE == 5
assert config.TRADINGVIEW_WEBHOOK_SECRET == "test_secret"
print("✓ Configuration loaded correctly")

# Test 2: Safe order module
print("\n[2/7] Testing safe order submission...")
from safe_order import submit_safe_order
result = submit_safe_order("BTC-USD", "buy", 50.0, "test_order_1")
assert result["status"] == "dry_run"
print(f"✓ Order submitted: {result['message']}")

# Test 3: Order size limit
print("\n[3/7] Testing order size limit...")
result = submit_safe_order("ETH-USD", "buy", 150.0, "test_order_2")
assert result["status"] == "rejected"
assert "MAX_ORDER_USD" in result["error"]
print("✓ Order size limit enforced")

# Test 4: Rate limiting
print("\n[4/7] Testing rate limiting...")
# Create a fresh instance to reset rate limiter
import importlib
import safe_order
importlib.reload(safe_order)

for i in range(5):
    result = safe_order.submit_safe_order("BTC-USD", "buy", 10.0, f"rate_test_{i}")
    if result["status"] != "dry_run":
        print(f"  Warning: Order {i} got status {result['status']}, expected dry_run")

result = safe_order.submit_safe_order("BTC-USD", "buy", 10.0, "rate_test_6")
assert result["status"] == "rate_limited"
print("✓ Rate limiting enforced")

# Test 5: Audit logging
print("\n[5/7] Testing audit logging...")
log_path = Path(temp_dir) / "orders.log"
assert log_path.exists()
with open(log_path, 'r') as f:
    logs = [json.loads(line) for line in f]
assert len(logs) >= 6  # At least 6 orders logged
print(f"✓ Audit log created with {len(logs)} entries")

# Test 6: TradingView webhook
print("\n[6/7] Testing TradingView webhook...")
from flask import Flask
from tradingview_webhook import tradingview_bp, generate_test_signature

app = Flask(__name__)
app.register_blueprint(tradingview_bp)
client = app.test_client()

payload = {"symbol": "BTC-USD", "side": "buy", "size_usd": 50.0}
payload_json = json.dumps(payload, separators=(',', ':'))
signature = generate_test_signature(payload)

response = client.post(
    '/tradingview/webhook',
    data=payload_json,
    headers={
        'Content-Type': 'application/json',
        'X-Tv-Signature': signature
    }
)

assert response.status_code == 200
data = json.loads(response.data)
assert data["status"] == "success"
print("✓ TradingView webhook endpoint working")

# Test 7: MODE=LIVE safety checks
print("\n[7/7] Testing LIVE mode safety checks...")
os.environ["MODE"] = "LIVE"
os.environ["COINBASE_ACCOUNT_ID"] = ""

# Reload modules to pick up new env vars
import importlib
import safe_order
import config as config_module
importlib.reload(config_module)
importlib.reload(safe_order)

result = safe_order.submit_safe_order("BTC-USD", "buy", 10.0)
if result["status"] != "rejected":
    print(f"  Got status: {result['status']}, error: {result.get('error', 'N/A')}")
assert result["status"] == "rejected"
assert "COINBASE_ACCOUNT_ID" in result["error"]
print("✓ LIVE mode safety checks working")

# Cleanup
print("\n" + "=" * 60)
print("All integration tests passed! ✅")
print("=" * 60)

import shutil
shutil.rmtree(temp_dir)
