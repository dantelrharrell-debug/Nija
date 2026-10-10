"""Fail-closed NIJA course-portal integration and asset integrity tests."""
from __future__ import annotations
import hashlib
import io
import json
import zipfile

import pytest
from sqlalchemy import create_engine

from course_portal import PortalStore, validate_bundle


def test_course_routes_do_not_grant_anonymous_access(tmp_path, monkeypatch):
    import billing_service as billing
    from billing_service_store import BillingServiceStore

    monkeypatch.setenv("BILLING_DATABASE_URL", f"sqlite:///{tmp_path / 'app.db'}")
    monkeypatch.setenv("NIJA_COURSE_DELIVERY_ENABLED", "false")
    store = BillingServiceStore(f"sqlite:///{tmp_path / 'app.db'}")
    app = billing.create_app(store)
    client = app.test_client()

    assert client.get("/course-portal/").status_code == 200
    assert client.get("/course-portal/library").status_code == 303
    resp = client.get("/course-portal/file/NIJA_Trading_Foundations_eBook.pdf")
    assert resp.status_code == 403
    assert resp.get_json()["error"] == "verified_course_access_required"
    assert client.get("/course-portal/thank-you").status_code == 200
    assert b"Payment Verified" not in client.get("/course-portal/thank-you").data
    assert client.get("/course-portal/thank-you?session_id=cs_fake").status_code == 200
    assert b"Payment Verified" not in client.get("/course-portal/thank-you?session_id=cs_fake").data
    assert client.get("/course-portal/readyz").get_json()["ready"] is False
    assert client.post("/course-portal/admin/import").status_code == 403
    assert client.post("/course-portal/admin/retry").status_code == 403


def test_email_recovery_is_generic_for_unknown_customer(tmp_path, monkeypatch):
    import billing_service as billing
    from billing_service_store import BillingServiceStore
    monkeypatch.setenv("BILLING_DATABASE_URL", f"sqlite:///{tmp_path / 'app.db'}")
    monkeypatch.setenv("NIJA_COURSE_DELIVERY_ENABLED", "false")
    store = BillingServiceStore(f"sqlite:///{tmp_path / 'app.db'}")
    client = billing.create_app(store).test_client()
    resp = client.post("/course-portal/recover", data={"email": "unknown@example.com"})
    assert resp.status_code == 202
    assert b"If this email has a verified course purchase" in resp.data


def test_one_time_magic_tokens_cannot_be_reused(tmp_path):
    store = PortalStore(create_engine(f"sqlite:///{tmp_path / 'portal.db'}"))
    token = store.mint("cs_example")
    assert store.consume(token) == "cs_example"
    assert store.consume(token) is None


def test_initial_delivery_token_is_stable_for_retries(tmp_path, monkeypatch):
    monkeypatch.setenv("NIJA_COURSE_SESSION_SECRET", "S" * 48)
    store = PortalStore(create_engine(f"sqlite:///{tmp_path / 'portal.db'}"))
    first = store.mint_initial("cs_example")
    assert first == store.mint_initial("cs_example")
    assert store.consume(first) == "cs_example"
    assert store.consume(first) is None


def test_bundle_integrity_and_reject_modified_asset(monkeypatch):
    import course_portal as course
    pdf = b"%PDF-1.4\nreference example"
    mp3 = b"ID3" + b"\x00" * 12
    good = {"Sample.pdf": pdf, "Sample.mp3": mp3}
    hashes = {name: hashlib.sha256(blob).hexdigest() for name, blob in good.items()}
    monkeypatch.setattr(course, "ALLOWED", hashes)

    def archive(blobs):
        b = io.BytesIO()
        with zipfile.ZipFile(b, "w") as z:
            for filename, content in blobs.items():
                z.writestr(filename, content)
            z.writestr("file_manifest.json", json.dumps([
                {"filename": filename, "sha256": digest}
                for filename, digest in hashes.items()
            ]))
        return b.getvalue()

    ok = archive(good)
    assert validate_bundle(ok) == hashlib.sha256(ok).hexdigest()

    damaged = archive({"Sample.pdf": pdf, "Sample.mp3": mp3 + b"X"})
    with pytest.raises(ValueError, match="asset_digest_mismatch"):
        validate_bundle(damaged)

    with pytest.raises(ValueError):
        validate_bundle(b"not a zip")


def test_authenticated_library_serves_only_purchased_content(tmp_path, monkeypatch):
    import billing_service as billing
    import course_portal as portal
    from billing_service_store import BillingServiceStore
    from itsdangerous import URLSafeTimedSerializer

    monkeypatch.setenv("BILLING_DATABASE_URL", f"sqlite:///{tmp_path / 'authed.db'}")
    monkeypatch.setenv("NIJA_COURSE_DELIVERY_ENABLED", "true")
    monkeypatch.setenv("NIJA_COURSE_SESSION_SECRET", "test-session-secret-" * 4)
    monkeypatch.setattr(portal.PortalStore, "has_bundle", lambda self: True)
    monkeypatch.setattr(portal.PortalStore, "asset_bytes",
                        lambda self, filename: b"%PDF-1.4\\nVerified" if filename.endswith(".pdf") else b"ID3test")
    monkeypatch.setattr(portal, "_valid_paid",
                        lambda sid: {"customer_email": "buyer@example.com"} if sid == "cs_good" else None)
    store = BillingServiceStore(f"sqlite:///{tmp_path / 'authed.db'}")
    app = billing.create_app(store)
    client = app.test_client()
    assert client.get("/course-portal/file/NIJA_Trading_Foundations_eBook.pdf", base_url="https://localhost").status_code == 403
    signer = URLSafeTimedSerializer("test-session-secret-" * 4, salt="nija-foundations-portal-v1")
    cookie = signer.dumps({"sid": "cs_good", "email": "buyer@example.com"})
    client.set_cookie("nija_foundations_session", cookie, path="/course-portal", secure=True)

    assert client.get("/course-portal/library", base_url="https://localhost").status_code == 200
    pdf = client.get("/course-portal/file/NIJA_Trading_Foundations_eBook.pdf", base_url="https://localhost")
    assert pdf.status_code == 200
    assert pdf.content_type.startswith("application/pdf")
    audio = client.get("/course-portal/file/NIJA_AI_Trading_Foundations_Final_Audiobook_Under_50MB.mp3", base_url="https://localhost")
    assert audio.status_code == 200
    assert audio.content_type.startswith("audio/mpeg")

    monkeypatch.setattr(portal, "_valid_paid", lambda sid: None)
    assert client.get("/course-portal/file/NIJA_Trading_Foundations_eBook.pdf", base_url="https://localhost").status_code == 403



def test_claim_token_survives_disabled_and_unverified_payment(tmp_path, monkeypatch):
    """A valid one-time link must not be burned by service/payment outages."""
    import billing_service as billing
    import course_portal as portal
    from billing_service_store import BillingServiceStore

    monkeypatch.setenv("BILLING_DATABASE_URL", f"sqlite:///{tmp_path / 'claim.db'}")
    monkeypatch.setenv("NIJA_COURSE_SESSION_SECRET", "test-session-secret-" * 4)
    monkeypatch.setenv("NIJA_COURSE_DELIVERY_ENABLED", "false")
    monkeypatch.setattr(portal.PortalStore, "has_bundle", lambda self: True)
    store = BillingServiceStore(f"sqlite:///{tmp_path / 'claim.db'}")
    app = billing.create_app(store)
    client = app.test_client()
    tokens = app.config["COURSE_PORTAL_STORE"]

    sid = "cs_claim_only_once"
    token = tokens.mint(sid)
    claim_url = f"/course-portal/claim?token={token}"

    # Disabled delivery must not consume the token.
    assert client.get(claim_url, base_url="https://localhost").status_code == 403
    assert tokens.inspect_unconsumed(token) == sid

    # Even when the portal is up, an unverified payment cannot burn the link.
    monkeypatch.setenv("NIJA_COURSE_DELIVERY_ENABLED", "true")
    monkeypatch.setattr(portal, "_valid_paid", lambda _sid: None)
    assert client.get(claim_url, base_url="https://localhost").status_code == 403
    assert tokens.inspect_unconsumed(token) == sid

    # Upon authoritative payment verification the token works exactly once.
    monkeypatch.setattr(portal, "_valid_paid",
                        lambda query_sid: {"customer_email": "buyer@example.com"}
                        if query_sid == sid else None)
    accepted = client.get(claim_url, base_url="https://localhost")
    assert accepted.status_code == 303
    assert accepted.headers["Location"] == "/course-portal/library"
    assert tokens.inspect_unconsumed(token) is None
    assert client.get(claim_url, base_url="https://localhost").status_code == 403
