import unittest
from scripts.nija_ionos_lead_rule_audit import audit

class RuleAuditTests(unittest.TestCase):
    def secure(self):
        return [{"name": name, **{field: None for field in fields}}
                for name, fields in __import__("scripts.nija_ionos_lead_rule_audit",
                fromlist=["SENSITIVE"]).SENSITIVE.items()]

    def test_secure(self):
        self.assertEqual(audit(self.secure()), [])

    def test_public_receipt_creation_is_blocked(self):
        rows = self.secure()
        next(row for row in rows if row["name"] == "nija_lead_delivery")["createRule"] = ""
        self.assertTrue(any("nija_lead_delivery.createRule" in x for x in audit(rows)))

    def test_conditional_receipt_creation_requires_review(self):
        rows = self.secure()
        next(row for row in rows if row["name"] == "nija_lead_delivery")["createRule"] = "@request.auth.id != ''"
        self.assertTrue(audit(rows))

    def test_missing_metadata_fails_closed(self):
        self.assertTrue(audit([]))
        self.assertTrue(audit([{"name": "nija_lead_delivery"}]))
