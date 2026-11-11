import unittest
from scripts.course_profit_probe import classify_profit_probe

class ProfitProbeTests(unittest.TestCase):
    def test_configured_unauthorized(self):
        self.assertEqual(classify_profit_probe(401, {"error": "administrator_authorization_required"}), "configured_auth_denied")
    def test_unconfigured_is_not_auth_verified(self):
        self.assertEqual(classify_profit_probe(503, {"status": "unavailable", "reason": "profit_reporting_not_configured"}), "reporting_disabled_fail_closed")
    def test_generic_proxy_503_fails(self):
        self.assertEqual(classify_profit_probe(503, {}), "failed")
    def test_503_with_financial_data_fails(self):
        self.assertEqual(classify_profit_probe(503, {"status":"unavailable","reason":"profit_reporting_not_configured","net_profit_usd":"100"}), "failed")
    def test_public_200_fails(self):
        self.assertEqual(classify_profit_probe(200, {"net_profit_usd":1}), "failed")
    def test_wrong_401_fails(self):
        self.assertEqual(classify_profit_probe(401, {}), "failed")

if __name__ == "__main__":
    unittest.main()
