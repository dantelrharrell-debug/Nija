import unittest
from website_revenue_attribution import summarize

class RevenueAttributionTests(unittest.TestCase):
    def test_verified_revenue_and_deduplication(self):
        events = [
            {"type":"visit","event_id":"v1","visitor_id":"browser-1"},
            {"type":"qualified_lead","event_id":"l1","lead_id":"lead-1","visitor_id":"browser-1"},
            {"type":"revenue","event_id":"pay1","verified":True,"source":"stripe","amount_usd":"50.00"},
            {"type":"revenue","event_id":"pay1","verified":True,"source":"stripe","amount_usd":"50.00"},
            {"type":"refund","event_id":"r1","verified":True,"source":"stripe","amount_usd":"10.00"},
            {"type":"revenue","event_id":"fake","verified":False,"source":"stripe","amount_usd":"900.00"},
        ]
        data = summarize(events)
        self.assertEqual(data["unique_visitors"], 1)
        self.assertEqual(data["unique_qualified_leads"], 1)
        self.assertEqual(data["net_verified_revenue_usd"], "40.00")
        self.assertEqual(data["revenue_per_visitor_usd"], "40.00")
        self.assertEqual(data["rejected_events"], 1)

    def test_no_synthetic_zero_denominator(self):
        data = summarize([{"type":"revenue","event_id":"a","verified":True,"source":"clickbank","amount_usd":"99.00"}])
        self.assertIsNone(data["revenue_per_visitor_usd"])
        self.assertIsNone(data["revenue_per_qualified_lead_usd"])

    def test_untrusted_or_invalid_amount(self):
        data = summarize([
            {"type":"revenue","event_id":"a","verified":True,"source":"browser","amount_usd":"8.00"},
            {"type":"revenue","event_id":"b","verified":True,"source":"stripe","amount_usd":"1.001"},
        ])
        self.assertEqual(data["net_verified_revenue_usd"], "0.00")
        self.assertEqual(data["rejected_events"], 2)

if __name__ == "__main__":
    unittest.main()
