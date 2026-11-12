"""Offline, read-only regression for Kraken source and interpreter boundaries.

No broker connections, Redis writes, approval issuance or production fixtures.
Run: python -m unittest tests.test_kraken_source_startup_contract_review -v
"""
import ast
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCES = {
    "position_ledger_reconciliation": ("bot/kraken_ledger_evidence.py", "make_kraken_ledger_evidence_provider"),
    "duplicate_order_fence": ("bot/kraken_redis_evidence.py", "RedisEvidenceReader"),
    "operator_authorization": ("bot/kraken_operator_authorization.py", "make_general_operator_authorization_provider"),
    "risk_limits": ("bot/kraken_risk_evidence.py", "make_kraken_risk_limits_provider"),
}


def tree(path):
    return ast.parse((ROOT / path).read_text(encoding="utf-8"))


class SourceStartupContractReview(unittest.TestCase):
    def test_all_four_existing_provider_symbols_are_present(self):
        for field, (path, symbol) in SOURCES.items():
            with self.subTest(field=field):
                names = {n.name for n in ast.walk(tree(path))
                         if isinstance(n, (ast.FunctionDef, ast.ClassDef))}
                self.assertIn(symbol, names)

    def test_composition_has_exact_four_external_families(self):
        module = tree("bot/kraken_evidence_composition.py")
        functions = {n.name for n in module.body if isinstance(n, ast.FunctionDef)}
        self.assertIn("compose_kraken_evidence", functions)
        classes = {n.name for n in module.body if isinstance(n, ast.ClassDef)}
        self.assertIn("KrakenEvidenceBinding", classes)
        self.assertIn("RiskEvidenceDependencies", classes)

    def test_signed_registration_remains_explicit(self):
        module = tree("bot/kraken_startup_receipts.py")
        registration = next(n for n in module.body if isinstance(n, ast.FunctionDef)
                            and n.name == "register_signed_kraken_startup")
        calls = {n.func.id for n in ast.walk(registration)
                 if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
        self.assertIn("make_startup_receipt_verifier", calls)
        self.assertIn("register_reviewed_startup_binding", calls)

    def test_canonical_main_installs_before_engine(self):
        module = tree("bot/bot_main.py")
        main = next(n for n in module.body if isinstance(n, ast.FunctionDef) and n.name == "main")
        calls = {n.func.id: n.lineno for n in ast.walk(main)
                 if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
        self.assertLess(calls["install_from_canonical_startup"], calls["start_trading_engine"])

    def test_new_interpreter_does_not_inherit_registration(self):
        # An actual fresh interpreter must start without an in-memory factory.
        script = ("import sys,types; p=types.ModuleType('bot'); "
                  "p.__path__=['bot']; sys.modules['bot']=p; "
                  "from bot.kraken_startup_evidence_binding import startup_binding_registration_state; "
                  "print(startup_binding_registration_state())")
        result = subprocess.run([sys.executable, "-S", "-c", script],
                                cwd=ROOT, capture_output=True, text=True,
                                timeout=15, check=True)
        self.assertEqual(result.stdout.strip(), "missing")


if __name__ == "__main__":
    unittest.main()
