"""Offline v515 report and durable entitlement regressions; no provider calls."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import os
import tempfile
import unittest
from unittest.mock import patch

from game_sandbox.ionos import PublishedGame
from game_sandbox.service import Config, Denied, Manifest, Sandbox
from game_sandbox.v515 import MODULE_DIGESTS, SOURCE_SHA256, V515Game, build_v515_report


def completed_run() -> dict:
    """The all-hold regression previously scored 50 in the older backend."""
    return {"mode": "standard", "level": "beginner", "dayNum": 0,
            "challenges": [[{"action": "hold", "stop": r % 3 == 0} for r in range(12)] for _ in range(6)]}


class ProviderFixture:
    """Deterministic provider boundary, explicitly not a Stripe sandbox test."""

    def __init__(self) -> None:
        self.calls = 0
        self.session = {}
        self.lines = {}

    def price(self, price_id: str) -> dict:
        return {"id": price_id, "product": "prod_v515_fixture", "active": True,
                "livemode": False, "type": "one_time", "unit_amount": 100, "currency": "usd"}

    def create(self, params: dict, idempotency_key: str) -> dict:
        self.calls += 1
        self.session = {"id": "cs_test_v515_fixture", "livemode": False, "mode": "payment",
                        "url": "https://checkout.stripe.com/c/test_fixture", "status": "complete",
                        "payment_status": "paid", "amount_total": 100, "currency": "usd",
                        "client_reference_id": params["client_reference_id"], "metadata": params["metadata"],
                        "payment_intent": {"id": "pi_v515_fixture", "status": "succeeded",
                                           "amount_received": 100, "currency": "usd", "livemode": False,
                                           "latest_charge": {"status": "succeeded", "paid": True,
                                                             "livemode": False, "amount_refunded": 0,
                                                             "refunded": False, "disputed": False}}}
        self.lines = {"has_more": False, "data": [{"quantity": 1, "amount_total": 100,
                      "currency": "usd", "price": {"id": "price_v515_fixture", "product": "prod_v515_fixture"}}]}
        return deepcopy(self.session)

    def purchase(self, session_id: str) -> tuple[dict, dict]:
        return deepcopy(self.session), deepcopy(self.lines)

    def event(self, raw: bytes, signature: str, secret: str) -> dict:
        if raw != b"fixture" or signature != "fixture":
            raise Denied("invalid_fixture_signature")
        return {"id": "evt_v515_fixture", "livemode": False, "type": "checkout.session.completed",
                "data": {"object": deepcopy(self.session)}}


class V515Tests(unittest.TestCase):
    def test_frontend_manifest_must_match_trusted_backend_version(self) -> None:
        from game_sandbox.preview_assets import PreviewAssets

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "assets").mkdir()
            assets = {"index.html": b"<main>v515 fixture</main>", "assets/game.js": b"// fixture"}
            for name, content in assets.items():
                (root / name).write_bytes(content)
            manifest = {"version": 1, "game_manifest": V515Game().digest,
                        "files": {name: hashlib.sha256(content).hexdigest() for name, content in assets.items()}}
            raw = json.dumps(manifest).encode()
            (root / "manifest.json").write_bytes(raw)
            pin = hashlib.sha256(raw).hexdigest()
            self.assertEqual(PreviewAssets(root, pin, V515Game().digest).manifest_sha256, pin)
            with self.assertRaisesRegex(ValueError, "preview_contract_required"):
                PreviewAssets(root, pin, PublishedGame().digest)
            with self.assertRaisesRegex(ValueError, "game_manifest_pin_required"):
                PreviewAssets(root, pin, "")

    def test_environment_selection_requires_exact_v515_manifest_pin(self) -> None:
        from game_sandbox.app import from_environment

        with tempfile.TemporaryDirectory() as directory:
            values = {"NIJA_IQ_SANDBOX_DATABASE": str(Path(directory) / "trading_iq_sandbox.sqlite3"),
                      "NIJA_IQ_SANDBOX_ORIGIN": "https://fixture.example",
                      "NIJA_IQ_SANDBOX_STRIPE_KEY": "sk_test_" + "fixture",
                      "NIJA_IQ_SANDBOX_WEBHOOK_SECRET": "whsec_" + "fixture",
                      "NIJA_IQ_SANDBOX_PRICE_ID": "price_v515_fixture",
                      "NIJA_IQ_SANDBOX_PRODUCT_ID": "prod_v515_fixture",
                      "NIJA_IQ_SANDBOX_ENABLED": "true", "NIJA_IQ_SANDBOX_GAME": "v515",
                      "NIJA_IQ_SANDBOX_MANIFEST_SHA256": V515Game().digest}
            with patch.dict(os.environ, values, clear=True), \
                    patch("game_sandbox.app.StripeGateway", return_value=ProviderFixture()), \
                    patch("game_sandbox.app.create_app", side_effect=lambda service: service):
                service = from_environment()
                self.assertIsInstance(service.manifest, V515Game)
                self.assertIs(service.report_builder, build_v515_report)
                os.environ["NIJA_IQ_SANDBOX_MANIFEST_SHA256"] = PublishedGame().digest
                with self.assertRaisesRegex(Denied, "reviewed_manifest_pin_required"):
                    from_environment()

    def test_new_source_identity_does_not_reuse_old_entitlements(self) -> None:
        game = V515Game()
        self.assertNotEqual(game.digest, PublishedGame().digest)
        self.assertEqual(len(game.rounds), 72)
        self.assertIn("v515", game.version)

    def test_copy_revision_cannot_reopen_pre_revision_runs(self) -> None:
        original = Manifest({
            "version": "ionos-v515-iq72-" + SOURCE_SHA256[:16],
            "source_sha256": SOURCE_SHA256,
            "structure": "12_per_challenge",
            "challenges": [{"rounds": [{"id": f"challenge_{i}_round_{j}", "choices": 6}
                                       for j in range(12)]} for i in range(6)],
        })
        self.assertNotEqual(original.digest, V515Game().digest)
        with tempfile.TemporaryDirectory() as directory:
            config = Config(database=str(Path(directory) / "trading_iq_sandbox.sqlite3"),
                            origin="https://fixture.example", key="sk_test_" + "fixture",
                            webhook_secret="whsec_" + "fixture", price="price_v515_fixture",
                            product="prod_v515_fixture", enabled=True)
            provider = ProviderFixture()
            old = Sandbox(config, original, provider, lambda payload: {})
            run_id, owner, _ = old.start(True)
            revised = Sandbox(config, V515Game(), provider, build_v515_report)
            with self.assertRaisesRegex(Denied, "ownership_required"):
                revised.report(run_id, owner)
            self.assertEqual(provider.calls, 0)

    def test_tampered_report_copy_is_rejected(self) -> None:
        with patch.dict(MODULE_DIGESTS, {"tiq_report.mjs": "0" * 64}):
            with self.assertRaisesRegex(Denied, "integrity_mismatch"):
                V515Game()

    def test_report_matches_approved_v515_instead_of_legacy_score(self) -> None:
        result = build_v515_report(completed_run())
        self.assertEqual(result["report"]["tradingIQ"], 93)
        self.assertEqual(sum(len(c["decisions"]) for c in result["report"]["challenges"]), 72)
        self.assertNotIn("<script", result["download_html"].lower())

    def test_tampered_source_is_rejected(self) -> None:
        with patch.dict(MODULE_DIGESTS, {"tiq_scoring.mjs": "0" * 64}):
            with self.assertRaisesRegex(Denied, "integrity_mismatch"):
                V515Game()

    def test_browser_score_and_incomplete_history_are_rejected(self) -> None:
        for payload in [dict(completed_run(), score=100), dict(completed_run(), challenges=[])]:
            with self.subTest(payload_keys=list(payload)):
                with self.assertRaises(Denied):
                    build_v515_report(payload)

    def test_entitlement_retry_refund_and_dispute_with_canonical_report(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = Config(database=str(Path(directory) / "trading_iq_sandbox.sqlite3"),
                            origin="https://fixture.example", key="sk_test_" + "fixture",
                            webhook_secret="whsec_" + "fixture", price="price_v515_fixture",
                            product="prod_v515_fixture", enabled=True)
            provider = ProviderFixture()
            service = Sandbox(config, V515Game(), provider, build_v515_report)
            run_id, owner, csrf = service.start(True)
            service.complete(run_id, owner, csrf, completed_run())
            service.checkout(run_id, owner, csrf)
            service.checkout(run_id, owner, csrf)
            self.assertEqual(provider.calls, 1)
            with self.assertRaisesRegex(Denied, "verified_webhook_required"):
                service.report(run_id, owner)
            service.webhook(b"fixture", "fixture")
            service.webhook(b"fixture", "fixture")
            self.assertEqual(service.report(run_id, owner)["report"]["tradingIQ"], 93)
            with self.assertRaisesRegex(Denied, "ownership_required"):
                service.report(run_id, "0" * 64)
            with service.db() as db:
                self.assertEqual(db.execute("SELECT COUNT(*) FROM events").fetchone()[0], 1)
            charge = provider.session["payment_intent"]["latest_charge"]
            for field in ["refunded", "disputed"]:
                charge[field] = True
                with self.assertRaisesRegex(Denied, "payment_reversed_or_unverified"):
                    service.report(run_id, owner)
                charge[field] = False

    def test_v515_storage_cannot_reopen_old_manifest_run(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = Config(database=str(Path(directory) / "trading_iq_sandbox.sqlite3"),
                            origin="https://fixture.example", key="sk_test_" + "fixture",
                            webhook_secret="whsec_" + "fixture", price="price_v515_fixture",
                            product="prod_v515_fixture", enabled=True)
            provider = ProviderFixture()
            old = Sandbox(config, PublishedGame(), provider, lambda payload: {})
            run_id, owner, _ = old.start(True)
            current = Sandbox(config, V515Game(), provider, build_v515_report)
            with self.assertRaisesRegex(Denied, "ownership_required"):
                current.report(run_id, owner)


if __name__ == "__main__":
    unittest.main()
