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



def _synthetic_private_course_bundle(monkeypatch):
    import course_portal as course
    files = {
        "unit.pdf": b"%PDF-1.6\n" + b"long-form-risk-exercise-" * 250,
        "audio.mp3": b"ID3" + b"private-audio-" * 300,
    }
    expected = {name: hashlib.sha256(value).hexdigest() for name, value in files.items()}
    monkeypatch.setattr(course, "ALLOWED", expected)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, value in files.items():
            archive.writestr(name, value)
        archive.writestr("file_manifest.json", json.dumps([
            {"filename": name, "sha256": digest} for name, digest in expected.items()
        ]))
    return files, buffer.getvalue()


def test_isolated_chunked_course_import_is_integrity_checked_and_idempotent(tmp_path, monkeypatch):
    import course_portal as course
    from sqlalchemy import select, func
    monkeypatch.setenv("NIJA_COURSE_SANDBOX_MODE", "true")
    monkeypatch.setenv("NIJA_COURSE_ASSET_CHUNKS", "true")
    monkeypatch.setattr(course, "CHUNK_BYTES", 256)
    originals, archive = _synthetic_private_course_bundle(monkeypatch)
    digest = course.validate_bundle(archive)
    engine = create_engine(f"sqlite:///{tmp_path / 'chunks.db'}")
    store = PortalStore(engine)
    assert not store.has_bundle()
    store.import_bundle(archive, digest)
    assert store.has_bundle()
    assert store.asset_bytes("NIJA_Foundations_Customer_Package.zip") == archive
    assert store.asset_bytes("unit.pdf") == originals["unit.pdf"]
    assert store.asset_bytes("audio.mp3") == originals["audio.mp3"]
    with engine.connect() as conn:
        assert conn.execute(select(func.count()).select_from(store.assets)).scalar_one() == 0
        parts = conn.execute(select(func.count()).select_from(store.asset_chunks)).scalar_one()
        assert parts > 2
    # New process instance, same DB: archive remains available and private.
    assert PortalStore(engine).asset_bytes("unit.pdf") == originals["unit.pdf"]
    store.import_bundle(archive, digest)
    with engine.connect() as conn:
        assert conn.execute(select(func.count()).select_from(store.asset_chunks)).scalar_one() == parts
    with pytest.raises(ValueError, match="asset_digest_mismatch"):
        store.import_bundle(archive, "0" * 64)


def test_chunked_course_write_interruption_does_not_publish_partial_archive(tmp_path, monkeypatch):
    import course_portal as course
    from sqlalchemy import event
    monkeypatch.setenv("NIJA_COURSE_SANDBOX_MODE", "true")
    monkeypatch.setenv("NIJA_COURSE_ASSET_CHUNKS", "true")
    monkeypatch.setattr(course, "CHUNK_BYTES", 512)
    originals, archive = _synthetic_private_course_bundle(monkeypatch)
    engine = create_engine(f"sqlite:///{tmp_path / 'interrupted.db'}")
    store = PortalStore(engine)
    count = [0]

    def simulate_database_restart(_conn, _cursor, statement, _params, _ctx, _executemany):
        if "INSERT INTO billing_course_private_asset_chunks" in statement:
            count[0] += 1
            if count[0] == 4:
                raise RuntimeError("simulated loss of database worker")

    event.listen(engine, "before_cursor_execute", simulate_database_restart)
    try:
        with pytest.raises(RuntimeError, match="simulated loss"):
            store.import_bundle(archive, course.validate_bundle(archive))
    finally:
        event.remove(engine, "before_cursor_execute", simulate_database_restart)
    assert not store.has_bundle()
    assert store.asset_bytes("unit.pdf") is None
    # Re-upload resumes matching immutable pieces without publishing partial rows.
    store.import_bundle(archive, course.validate_bundle(archive))
    assert store.has_bundle()
    assert store.asset_bytes("unit.pdf") == originals["unit.pdf"]


def test_chunked_course_detects_corrupt_part_without_serving_private_data(tmp_path, monkeypatch):
    import course_portal as course
    from sqlalchemy import update
    monkeypatch.setenv("NIJA_COURSE_SANDBOX_MODE", "true")
    monkeypatch.setenv("NIJA_COURSE_ASSET_CHUNKS", "true")
    monkeypatch.setattr(course, "CHUNK_BYTES", 512)
    _, archive = _synthetic_private_course_bundle(monkeypatch)
    store = PortalStore(create_engine(f"sqlite:///{tmp_path / 'corrupt.db'}"))
    store.import_bundle(archive, course.validate_bundle(archive))
    with store.engine.begin() as conn:
        conn.execute(update(store.asset_chunks).where(
            store.asset_chunks.c.part_index == 0).values(data=b"corrupted-part"))
    assert store.asset_bytes("unit.pdf") is None
    assert store.asset_bytes("NIJA_Foundations_Customer_Package.zip") is None


def test_legacy_assets_remain_compatible_when_chunk_mode_enabled_later(tmp_path, monkeypatch):
    import course_portal as course
    monkeypatch.delenv("NIJA_COURSE_ASSET_CHUNKS", raising=False)
    _, archive = _synthetic_private_course_bundle(monkeypatch)
    store = PortalStore(create_engine(f"sqlite:///{tmp_path / 'legacy.db'}"))
    store.import_bundle(archive, course.validate_bundle(archive))
    assert store.has_bundle()
    monkeypatch.setenv("NIJA_COURSE_SANDBOX_MODE", "true")
    monkeypatch.setenv("NIJA_COURSE_ASSET_CHUNKS", "true")
    assert store.has_bundle()
    assert store.asset_bytes("NIJA_Foundations_Customer_Package.zip") == archive


def test_protected_course_upload_storage_failure_returns_safe_json(tmp_path, monkeypatch):
    import billing_service as billing
    import course_portal as course
    from billing_service_store import BillingServiceStore
    originals, archive = _synthetic_private_course_bundle(monkeypatch)
    monkeypatch.setenv("NIJA_COURSE_DELIVERY_ENABLED", "false")
    token = "test-only-operator-token-" * 3
    monkeypatch.setenv("NIJA_COURSE_UPLOAD_SECRET", token)
    monkeypatch.setenv("BILLING_DATABASE_URL", f"sqlite:///{tmp_path / 'error.db'}")
    app = billing.create_app(BillingServiceStore(f"sqlite:///{tmp_path / 'error.db'}"))
    course_store = app.config["COURSE_PORTAL_STORE"]
    def fails_before_committed(_archive, _digest):
        raise RuntimeError("server-private-diagnostic")
    monkeypatch.setattr(course_store, "import_bundle", fails_before_committed)
    client = app.test_client()
    reply = client.post(
        "/course-portal/admin/import",
        headers={"Authorization": "Bearer " + token},
        data={"package": (io.BytesIO(archive), "test-private.zip")},
        content_type="multipart/form-data")
    assert reply.status_code == 503
    assert reply.get_json() == {"error": "course_storage_unavailable"}
    assert b"server-private-diagnostic" not in reply.data
    assert not course_store.has_bundle()


def test_course_admin_preview_button_keeps_sensitive_order_data_server_side(tmp_path, monkeypatch):
    """Read-only status UI must require the existing operator token and show only counts."""
    import billing_service as billing
    from billing_service_store import BillingServiceStore
    monkeypatch.setenv("BILLING_DATABASE_URL", f"sqlite:///{tmp_path / 'preview.db'}")
    monkeypatch.setenv("NIJA_COURSE_DELIVERY_ENABLED", "false")
    app = billing.create_app(BillingServiceStore(f"sqlite:///{tmp_path / 'preview.db'}"))
    client = app.test_client()

    html = client.get("/course-portal/admin/").get_data(as_text=True)
    assert "Review Paid Test Orders (Read Only)" in html
    assert 'fetch("/course-portal/admin/preview"' in html
    assert '"Authorization":"Bearer "+input.value' in html
    assert "DRY RUN — NO ORDERS CHANGED" in html
    assert "paid_without_entitlement" in html
    assert "input.value=\"\"" in html
    denied = client.get("/course-portal/admin/preview")
    assert denied.status_code == 403
    assert denied.get_json() == {"error": "unauthorized"}


def _build_test_reconcile_app(tmp_path, monkeypatch):
    import billing_service as billing
    import course_portal as course
    from billing_service_store import BillingServiceStore
    from types import SimpleNamespace

    db = f"sqlite:///{tmp_path / 'two-tests.db'}"
    token = "sandbox-operator-token-" * 3
    monkeypatch.setenv("BILLING_DATABASE_URL", db)
    monkeypatch.setenv("NIJA_COURSE_SANDBOX_MODE", "true")
    monkeypatch.setenv("NIJA_COURSE_DELIVERY_ENABLED", "false")
    monkeypatch.setenv("NIJA_COURSE_UPLOAD_SECRET", token)
    monkeypatch.setattr(course.PortalStore, "has_bundle", lambda self: True)
    monkeypatch.setattr(course, "expected_course_identity",
                        lambda: ("plink_test", "price_test", "prod_test", False))
    monkeypatch.setattr(course, "expected_course_link", lambda: "plink_test")
    ids = ["cs_test_paid_one", "cs_test_paid_two", "cs_test_paid_three"]
    sessions = [{"id": x, "payment_link": "plink_test", "livemode": False,
                 "status": "complete", "payment_status": "paid"} for x in ids]
    session_list = lambda **_kw: {"data": sessions, "has_more": False}
    fake_stripe = SimpleNamespace(
        checkout=SimpleNamespace(Session=SimpleNamespace(list=session_list)))
    monkeypatch.setattr(course, "_stripe", lambda: fake_stripe)
    app = billing.create_app(BillingServiceStore(db))
    ledger = app.config["COURSE_LEDGER"]
    ledger.upsert(ids[0], "test@example.com", None, "pi_test_one", "paid", True)
    grant_calls = []
    def verified(_stripe, book, sid):
        grant_calls.append(sid)
        book.upsert(sid, "test@example.com", None, "pi_" + sid, "paid", True)
        return {"session_id": sid, "paid": True}
    monkeypatch.setattr(course, "reconcile_session", verified)
    monkeypatch.setattr(course, "on_course_payment",
                        lambda *_args: pytest.fail("customer email or queue unexpectedly invoked"))
    monkeypatch.setattr(course, "_email_access",
                        lambda *_args, **_kw: pytest.fail("outbound email unexpectedly invoked"))
    return app, token, ids, sessions, grant_calls


def test_two_missing_test_entitlements_reconcile_exactly_without_emails(tmp_path, monkeypatch):
    app, token, ids, _sessions, calls = _build_test_reconcile_app(tmp_path, monkeypatch)
    client = app.test_client()
    path = "/course-portal/admin/reconcile-test-missing"
    headers = {"Authorization": "Bearer " + token}
    assert client.post(path, json={"expected_session_ids": ids[1:]}).status_code == 403
    preview = client.get("/course-portal/admin/preview", headers=headers).get_json()
    assert preview["dry_run"] is True
    assert preview["counts"]["paid"] == 3
    assert preview["counts"]["already_reconciled"] == 1
    assert preview["counts"]["paid_without_entitlement"] == 2
    assert set(preview["missing_test_session_ids"]) == set(ids[1:])

    response = client.post(path, json={"expected_session_ids": ids[1:]}, headers=headers)
    assert response.status_code == 200
    assert response.get_json() == {
        "reconciled": 2, "email_sent": False,
        "delivery_enabled": False, "test_mode": True
    }
    assert set(calls) == set(ids[1:])
    recounted = client.get("/course-portal/admin/preview", headers=headers).get_json()
    assert recounted["counts"]["already_reconciled"] == 3
    assert recounted["counts"]["paid_without_entitlement"] == 0
    assert recounted["missing_test_session_ids"] == []
    assert client.post(path, json={"expected_session_ids": ids[1:]},
                       headers=headers).status_code == 409
    assert len(calls) == 2


def test_test_grant_reconciliation_fails_closed_on_mode_delivery_or_stale_preview(tmp_path, monkeypatch):
    import course_portal as course
    app, token, ids, sessions, calls = _build_test_reconcile_app(tmp_path, monkeypatch)
    c = app.test_client()
    p = "/course-portal/admin/reconcile-test-missing"
    h = {"Authorization": "Bearer " + token}
    for bad in [None, {}, {"expected_session_ids": ids},
                {"expected_session_ids": ids[:1]},
                {"expected_session_ids": [ids[1], ids[1]]},
                {"expected_session_ids": [ids[1], "cs_live_other"]}]:
        assert c.post(p, json=bad, headers=h).status_code == 400
    assert c.post(p, json={"expected_session_ids": [ids[0], ids[1]]},
                  headers=h).status_code == 409

    monkeypatch.setenv("NIJA_COURSE_DELIVERY_ENABLED", "true")
    assert c.post(p, json={"expected_session_ids": ids[1:]}, headers=h).status_code == 503
    monkeypatch.setenv("NIJA_COURSE_DELIVERY_ENABLED", "false")
    monkeypatch.setenv("NIJA_COURSE_SANDBOX_MODE", "false")
    assert c.post(p, json={"expected_session_ids": ids[1:]}, headers=h).status_code == 503
    monkeypatch.setenv("NIJA_COURSE_SANDBOX_MODE", "true")
    monkeypatch.setattr(course, "expected_course_identity",
                        lambda: ("plink_live", "price_live", "prod_live", True))
    assert c.post(p, json={"expected_session_ids": ids[1:]}, headers=h).status_code == 503
    assert calls == []
