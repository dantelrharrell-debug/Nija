"""Fail-closed regression checks for unsigned mobile generation."""
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]

class MobileIAPGuardTests(unittest.TestCase):
    def test_unavailable_dependency_absent(self):
        package = json.loads((ROOT / "package.json").read_text())
        for section in ("dependencies", "devDependencies"):
            self.assertNotIn("@capacitor-community/in-app-purchases", package.get(section, {}))

    def test_native_purchase_adapter_is_fail_closed(self):
        source = (ROOT / "frontend/static/js/iap-service.js").read_text()
        self.assertNotIn("from '@capacitor-community/in-app-purchases'", source)
        self.assertIn("async initialize() { return false; }", source)
        self.assertIn("async hasActiveSubscription() { return false; }", source)
        self.assertIn("async purchaseSubscription() { unavailable(); }", source)

    def test_no_legacy_checkout_or_unverified_success(self):
        source = (ROOT / "frontend/static/js/subscription-ui.js").read_text()
        self.assertNotIn("handleWebCheckout", source)
        self.assertNotIn("Subscription activated!", source)
        self.assertIn("No purchase has been made.", source)

if __name__ == "__main__":
    unittest.main()
