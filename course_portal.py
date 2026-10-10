"""NIJA Foundations: authenticated, fail-closed course delivery.

Separate from subscription entitlements and all trading/broker permissions.
Assets are stored in private billing Postgres; never publish ZIP/PDF/MP3 URLs.
"""
from __future__ import annotations

import hashlib
import hmac
import html
import io
import json
import logging
import os
import secrets
import time
import zipfile
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

import requests
from flask import Blueprint, current_app, jsonify, make_response, redirect, request, send_file
from sqlalchemy import Boolean, Column, DateTime, Integer, LargeBinary, MetaData, String, Table, Text, insert, select, update
from sqlalchemy.exc import IntegrityError

from course_fulfillment import COURSE_LINK, CourseLedger, reconcile_session

log = logging.getLogger("nija.billing.course_portal")
COOKIE = "nija_foundations_session"
BUNDLE = "foundations-customer-v1"
ALLOWED = {
    "04_NIJA_Video_and_Audiobook_Scripts.pdf": "d71de5c35dc3ce86ce3b3d079b4faafe9cd0e010600d94908a0084416fe8ccc1",
    "06_NIJA_Certificate_of_Completion.pdf": "3292378e9dac3ad45dcad4534ba2801da6033e4e3483015ec1e08375bfd48ade",
    "NIJA_12_Week_Trading_Practice_Journal.pdf": "726f7741b16634098435724ddfce3a8bd7822e199c93b36ca01c380bf2ea8e0d",
    "NIJA_AI_Trading_Foundations_Final_Audiobook_Under_50MB.mp3": "63df9831c4057bc966250ef487bca45f8ddaecd1e6a9debbef25326f6f811d96",
    "NIJA_Companion_Trading_Workbook.pdf": "bea77cfe213ce9abab738b0face6873af234815569c7e67bbca9c24c3aca63c5",
    "NIJA_Foundations_Start_Here.pdf": "e674016f8e14e0e11ca84262a9cd530c8190be209343a8efe43edfd3fc2dbc5d",
    "NIJA_Starter_Kit.pdf": "e617b689a300c3401f7609ff69d9eae8b08b584076c981721fa3b50cc45f938a",
    "NIJA_Trading_Foundations_eBook.pdf": "1fbec8ef0dfe46c0f15f9cc78a1db6ee656f6b346b6b80a20b8e8c97cdf24f38",
}
AUDIO = "NIJA_AI_Trading_Foundations_Final_Audiobook_Under_50MB.mp3"
MAX_ZIP = 58 * 1024 * 1024


def utcnow():
    return datetime.now(timezone.utc)


def validate_bundle(payload):
    """Validate *both* the manifest and all original bytes before private storage."""
    if not payload or len(payload) > MAX_ZIP:
        raise ValueError("package_size_invalid")
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as z:
            names = z.namelist()
            if len(names) != len(ALLOWED) + 1 or set(names) != set(ALLOWED) | {"file_manifest.json"}:
                raise ValueError("package_file_list_mismatch")
            if sum(i.file_size for i in z.infolist()) > 52 * 1024 * 1024:
                raise ValueError("uncompressed_size_limit")
            manifest = json.loads(z.read("file_manifest.json"))
            declared = {i["filename"]: i["sha256"] for i in manifest}
            if declared != ALLOWED:
                raise ValueError("manifest_mismatch")
            for name, digest in ALLOWED.items():
                data = z.read(name)
                if hashlib.sha256(data).hexdigest() != digest:
                    raise ValueError("asset_digest_mismatch")
                if name.endswith(".pdf") and not data.startswith(b"%PDF-"):
                    raise ValueError("invalid_pdf")
                if name.endswith(".mp3") and not (data.startswith(b"ID3") or data[:1] == b"\xff"):
                    raise ValueError("invalid_audio")
    except (zipfile.BadZipFile, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError("invalid_package") from exc
    return hashlib.sha256(payload).hexdigest()


class PortalStore:
    def __init__(self, engine):
        self.engine = engine
        m = MetaData()
        self.assets = Table(
            "billing_course_private_assets", m,
            Column("bundle_id", String(80), primary_key=True),
            Column("data", LargeBinary, nullable=False),
            Column("sha256", String(64), nullable=False),
            Column("updated_at", DateTime(timezone=True), nullable=False),
        )
        self.outbox = Table(
            "billing_course_mail_outbox", m,
            Column("session_id", String(128), primary_key=True),
            Column("email", String(320), nullable=False),
            Column("status", String(24), nullable=False),
            Column("attempts", Integer, nullable=False, default=0),
            Column("provider_id", String(128)),
            Column("last_error", Text),
            Column("updated_at", DateTime(timezone=True), nullable=False),
        )
        self.tokens = Table(
            "billing_course_magic_tokens", m,
            Column("token_hash", String(64), primary_key=True),
            Column("session_id", String(128), nullable=False),
            Column("expires_at", DateTime(timezone=True), nullable=False),
            Column("consumed_at", DateTime(timezone=True)),
        )
        self.ratelimits = Table(
            "billing_course_access_ratelimit", m,
            Column("key", String(64), primary_key=True),
            Column("attempts", Integer, nullable=False),
            Column("updated_at", DateTime(timezone=True), nullable=False),
        )
        m.create_all(engine)

    def has_bundle(self):
        with self.engine.connect() as conn:
            return conn.execute(select(self.assets.c.bundle_id).where(self.assets.c.bundle_id == BUNDLE)).first() is not None

    def import_bundle(self, payload, digest):
        with self.engine.begin() as conn:
            values = {"data": payload, "sha256": digest, "updated_at": utcnow()}
            if conn.execute(select(self.assets.c.bundle_id).where(self.assets.c.bundle_id == BUNDLE)).first():
                conn.execute(update(self.assets).where(self.assets.c.bundle_id == BUNDLE).values(**values))
            else:
                conn.execute(insert(self.assets).values(bundle_id=BUNDLE, **values))

    def asset_bytes(self, name):
        if name not in ALLOWED and name != "NIJA_Foundations_Customer_Package.zip":
            return None
        with self.engine.connect() as conn:
            payload = conn.execute(select(self.assets.c.data).where(self.assets.c.bundle_id == BUNDLE)).scalar_one_or_none()
        if payload is None:
            return None
        if name == "NIJA_Foundations_Customer_Package.zip":
            return payload
        with zipfile.ZipFile(io.BytesIO(payload)) as z:
            return z.read(name)

    def enqueue(self, sid, email):
        try:
            with self.engine.begin() as conn:
                conn.execute(insert(self.outbox).values(session_id=sid, email=email,
                    status="queued", attempts=0, updated_at=utcnow()))
        except IntegrityError:
            pass

    def pending(self, limit=10):
        stale = utcnow() - timedelta(minutes=15)
        with self.engine.connect() as conn:
            rows = conn.execute(select(self.outbox).where(
                ((self.outbox.c.status.in_(("queued", "error"))) |
                 ((self.outbox.c.status == "sending") &
                  (self.outbox.c.updated_at < stale))) &
                (self.outbox.c.attempts < 5)
            ).order_by(self.outbox.c.updated_at).limit(limit)).all()
            return [dict(r._mapping) for r in rows]

    def mark_sending(self, sid):
        stale = utcnow() - timedelta(minutes=15)
        with self.engine.begin() as conn:
            result = conn.execute(update(self.outbox).where(
                (self.outbox.c.session_id == sid) &
                ((self.outbox.c.status.in_(("queued", "error"))) |
                 ((self.outbox.c.status == "sending") &
                  (self.outbox.c.updated_at < stale))) &
                (self.outbox.c.attempts < 5)
            ).values(status="sending", attempts=self.outbox.c.attempts + 1, updated_at=utcnow()))
            return result.rowcount == 1

    def mint_initial(self, sid):
        # Stable across retries; Resend receives the same idempotency key + link.
        secret = os.environ["NIJA_COURSE_SESSION_SECRET"]
        digest = hmac.new(secret.encode(), ("delivery-v1:" + sid).encode(), hashlib.sha256).digest()
        import base64
        token = base64.urlsafe_b64encode(digest).decode().rstrip("=")
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        try:
            with self.engine.begin() as conn:
                conn.execute(insert(self.tokens).values(
                    token_hash=token_hash, session_id=sid,
                    expires_at=utcnow() + timedelta(days=7)))
        except IntegrityError:
            pass
        return token

    def mark_mail(self, sid, status, provider_id=None, error=None):
        with self.engine.begin() as conn:
            conn.execute(update(self.outbox).where(self.outbox.c.session_id == sid).values(
                status=status, provider_id=provider_id, last_error=(error or "")[:240],
                updated_at=utcnow()))

    def mint(self, sid, expiry_hours=48):
        token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        with self.engine.begin() as conn:
            conn.execute(insert(self.tokens).values(token_hash=token_hash,
                session_id=sid, expires_at=utcnow() + timedelta(hours=expiry_hours)))
        return token

    def inspect_unconsumed(self, token):
        """Check a recovery link without burning it during payment or service outages."""
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        with self.engine.connect() as conn:
            row = conn.execute(select(self.tokens).where(
                self.tokens.c.token_hash == token_hash
            )).first()
        if row is None:
            return None
        data = dict(row._mapping)
        expires = data["expires_at"]
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        if data["consumed_at"] is not None or expires <= utcnow():
            return None
        return data["session_id"]

    def consume(self, token):
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        with self.engine.begin() as conn:
            row = conn.execute(select(self.tokens).where(self.tokens.c.token_hash == token_hash)).first()
            if not row:
                return None
            data = dict(row._mapping)
            expires = data["expires_at"]
            if expires.tzinfo is None:
                expires = expires.replace(tzinfo=timezone.utc)
            if data["consumed_at"] or expires <= utcnow():
                return None
            updated = conn.execute(update(self.tokens).where(
                (self.tokens.c.token_hash == token_hash) &
                self.tokens.c.consumed_at.is_(None)
            ).values(consumed_at=utcnow()))
            return data["session_id"] if updated.rowcount == 1 else None

    def allow_recovery(self, email, ip):
        window = int(time.time() // 3600)
        key = hashlib.sha256((email + "|" + ip + "|" + str(window)).encode()).hexdigest()
        with self.engine.begin() as conn:
            row = conn.execute(select(self.ratelimits).where(self.ratelimits.c.key == key)).first()
            if row is None:
                conn.execute(insert(self.ratelimits).values(key=key, attempts=1, updated_at=utcnow()))
                return True
            attempts = row._mapping["attempts"]
            if attempts >= 3:
                return False
            conn.execute(update(self.ratelimits).where(self.ratelimits.c.key == key).values(
                attempts=attempts+1, updated_at=utcnow()))
            return True


def _enabled(app):
    # Content access remains available if the email provider is temporarily down.
    return os.getenv("NIJA_COURSE_DELIVERY_ENABLED", "false").lower() == "true" and \
        _signer() is not None and app.config["COURSE_PORTAL_STORE"].has_bundle()


def _email_ready(app):
    return _enabled(app) and bool(os.getenv("RESEND_API_KEY"))


def _stripe():
    # Existing billing-owned Stripe key; never use browser supplied Stripe keys.
    import stripe
    stripe.api_key = os.environ["STRIPE_SECRET_KEY"]
    return stripe


def _valid_paid(sid):
    ledger = current_app.config["COURSE_LEDGER"]
    record = ledger.get(sid)
    if not record or not record["granted"] or record["status"] != "paid":
        return None
    try:
        outcome = reconcile_session(_stripe(), ledger, sid)
    except Exception:
        log.exception("Course payment revalidation unavailable")
        return None
    if not outcome or not outcome["paid"]:
        return None
    return ledger.get(sid)


def _signer():
    from itsdangerous import URLSafeTimedSerializer
    secret = os.getenv("NIJA_COURSE_SESSION_SECRET", "")
    if len(secret) < 32:
        return None
    return URLSafeTimedSerializer(secret, salt="nija-foundations-portal-v1")


def _session_record():
    signer = _signer()
    if not signer:
        return None
    token = request.cookies.get(COOKIE)
    if not token:
        return None
    from itsdangerous import BadSignature, SignatureExpired
    try:
        info = signer.loads(token, max_age=30*24*3600)
    except (BadSignature, SignatureExpired):
        return None
    rec = _valid_paid(info.get("sid", ""))
    if not rec or not hmac.compare_digest(rec["customer_email"], info.get("email", "")):
        return None
    return rec


def _layout(title, body):
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        '<title>' + html.escape(title) + ' — NIJA Trading Foundations</title>'
        '<style>body{background:#0d1018;color:#fff;font:16px system-ui,sans-serif;'
        'max-width:850px;margin:50px auto;padding:22px;line-height:1.6}a{color:#f3ca6c}'
        '.card{border:1px solid #6b572a;border-radius:16px;padding:24px;margin:18px 0}'
        'button{padding:12px 22px;background:#d7ae47;color:#141414;border:0;border-radius:6px}'
        'input{padding:12px;min-width:240px}h1{color:#f2cb70}</style></head>'
        '<body><p><strong>NIJA AI TRADING</strong> · Education</p><h1>'
        + html.escape(title) + '</h1>' + body + '<p>Support: '
        '<a href="mailto:support@nijaaitrading.com">support@nijaaitrading.com</a></p>'
        '<small>Educational material only. No trading profits are guaranteed.</small></body></html>')


def _email_access(email, sid, token, *, delivery=False):
    key = os.getenv("RESEND_API_KEY", "")
    link = os.getenv("NIJA_COURSE_PUBLIC_URL", "https://nija-billing-api.onrender.com").rstrip("/") + \
        "/course-portal/claim?token=" + quote(token)
    if not key:
        raise RuntimeError("resend_not_configured")
    message = {
        "from": os.getenv("NIJA_COURSE_SENDER", "NIJA AI Trading <support@nijaaitrading.com>"),
        "to": [email], "subject": "Your NIJA Trading Foundations access is ready",
        "html": "<h2>NIJA Trading Foundations</h2><p>Your payment has been verified."
                " Use this one-time secure link to open your purchased materials:</p>"
                '<p><a href="' + html.escape(link, quote=True) + '">Open My Course</a></p>'
                "<p>This secure link expires in " + ("7 days" if delivery else "48 hours") +
                ". You can restore access later from the course portal.</p>"
                "<p>Includes your eBook, audiobook, workbook, fillable practice journal, "
                "scripts, certificate template, Start Here guide and bonus Starter Kit.</p>"
                "<p>This is educational material, not financial advice or a profit guarantee.</p>"
                "<p>Support: support@nijaaitrading.com</p>"
    }
    response = requests.post("https://api.resend.com/emails", json=message, headers={
        "Authorization": "Bearer " + key,
        "Content-Type": "application/json",
        "Idempotency-Key": ("nija-foundations-delivery-v1-" + sid if delivery else
                            "nija-foundations-recovery-v1-" + hashlib.sha256(token.encode()).hexdigest()),
    }, timeout=5)
    if response.status_code not in (200, 201):
        raise RuntimeError("provider_rejected_" + str(response.status_code))
    return response.json().get("id")


def _dispatch_one(sid, email):
    store = current_app.config["COURSE_PORTAL_STORE"]
    if not _email_ready(current_app) or not store.mark_sending(sid):
        return
    if not _valid_paid(sid):
        store.mark_mail(sid, "error", error="payment_not_verified")
        return
    try:
        token = store.mint_initial(sid)
        provider_id = _email_access(email, sid, token, delivery=True)
        if not provider_id:
            raise RuntimeError("provider_message_id_missing")
        store.mark_mail(sid, "sent", provider_id=provider_id)
    except Exception as exc:
        log.error("NIJA course delivery email unavailable: %s", type(exc).__name__)
        store.mark_mail(sid, "error", error=type(exc).__name__)


def on_course_payment(app, session_id):
    """Called after a signed Stripe event has been reconciled into the course ledger."""
    if not session_id:
        return
    with app.app_context():
        ledger = app.config["COURSE_LEDGER"].get(session_id)
        if not ledger or not ledger["granted"] or ledger["status"] != "paid":
            return
        store = app.config["COURSE_PORTAL_STORE"]
        store.enqueue(session_id, ledger["customer_email"])
        _dispatch_one(session_id, ledger["customer_email"])


def register_course_portal(app, billing_store):
    portal = Blueprint("nija_course_portal", __name__, url_prefix="/course-portal")
    store = PortalStore(billing_store.engine)
    app.config["COURSE_PORTAL_STORE"] = store

    @portal.get("/")
    def course_home():
        return _layout("Course Access", '<div class="card"><p>Already purchased? '
            'Enter the email used at checkout to receive a secure access link.</p>'
            '<form method="post" action="/course-portal/recover">'
            '<input type="email" name="email" autocomplete="email" required maxlength="320">'
            '<button type="submit">Email My Access Link</button></form></div>')

    @portal.post("/recover")
    def recover():
        email = (request.form.get("email") or "").strip().lower()[:320]
        ip = request.remote_addr or "unknown"
        if "@" in email and store.allow_recovery(email, ip) and _email_ready(current_app):
            ledger = current_app.config["COURSE_LEDGER"]
            with store.engine.connect() as conn:
                found = conn.execute(select(ledger.table.c.session_id).where(
                    (ledger.table.c.customer_email == email) &
                    (ledger.table.c.granted.is_(True))
                ).limit(5)).all()
            for r in found:
                sid = r[0]
                if _valid_paid(sid):
                    try:
                        token = store.mint(sid)
                        _email_access(email, sid, token)
                    except Exception:
                        log.exception("Course recovery email failed")
                    break
        return _layout("Check Your Email", "<p>If this email has a verified course purchase, "
            "you'll receive a secure access link. Please check your inbox and spam folder.</p>"), 202

    @portal.get("/claim")
    def claim():
        token = request.args.get("token", "")
        if not token or len(token) > 128:
            return _layout("Access Link Invalid", "<p>Request a new access link from the course portal.</p>"), 403
        signer = _signer()
        if not _enabled(current_app) or not signer:
            return _layout("Access Link Invalid", "<p>This link is expired, already used or unavailable. "
                '<a href="/course-portal/">Recover access</a>.</p>'), 403
        # Verify entitlement first. A transient Stripe failure or disabled
        # delivery must not permanently consume an otherwise valid access link.
        sid = store.inspect_unconsumed(token)
        rec = _valid_paid(sid) if sid else None
        if not rec or store.consume(token) != sid:
            return _layout("Access Link Invalid", "<p>This link is expired, already used or unavailable. "
                '<a href="/course-portal/">Recover access</a>.</p>'), 403
        cookie = signer.dumps({"sid": sid, "email": rec["customer_email"]})
        resp = make_response(redirect("/course-portal/library", code=303))
        resp.set_cookie(COOKIE, cookie, max_age=30*24*3600, secure=True,
                        httponly=True, samesite="Lax", path="/course-portal")
        resp.headers["Cache-Control"] = "no-store"
        return resp

    @portal.get("/thank-you")
    def thank_you():
        sid = (request.args.get("session_id") or "").strip()
        if not sid.startswith("cs_") or len(sid) > 128:
            return _layout("Verify Your Purchase", '<p>Course access is granted only after '
                'secure payment verification. <a href="/course-portal/">Restore an existing purchase</a>.</p>')
        if _enabled(current_app):
            rec = _valid_paid(sid)
            if rec:
                store.enqueue(sid, rec["customer_email"])
                _dispatch_one(sid, rec["customer_email"])
                return _layout("Payment Verified", "<p>Your payment was verified. "
                    "Check the email used at checkout for your secure course access link.</p>")
        return _layout("Payment Verification Pending", "<p>We have not confirmed this payment. "
            "Please check back or contact support; course access is not granted until verified.</p>")

    @portal.get("/library")
    def library():
        rec = _session_record() if _enabled(current_app) else None
        if not rec:
            return redirect("/course-portal/", code=303)
        entries = []
        for name in ALLOWED:
            label = ("Audiobook — listen or download" if name == AUDIO else
                     name.replace("NIJA_", "").replace("_", " ").replace(".pdf", ""))
            entries.append('<li><a href="/course-portal/file/' + quote(name) + '">' +
                           html.escape(label) + '</a></li>')
        player = '<audio controls preload="none" style="width:100%" src="/course-portal/file/' + quote(AUDIO) + '"></audio>'
        body = '<p>Welcome to your purchased education materials. Start with the Start Here guide.</p>'
        body += '<div class="card"><ul>' + "".join(entries) + '</ul>' + player + '</div>'
        body += '<p><a href="/course-portal/file/NIJA_Foundations_Customer_Package.zip">Download complete package</a></p>'
        body += '<p>Scripts are not finished lesson videos. The certificate is a template.</p>'
        return _layout("Your Course Library", body)

    @portal.get("/file/<filename>")
    def file_download(filename):
        rec = _session_record() if _enabled(current_app) else None
        if not rec:
            return jsonify({"error": "verified_course_access_required"}), 403
        data = store.asset_bytes(filename)
        if data is None:
            return jsonify({"error": "asset_not_available"}), 404
        mime = ("audio/mpeg" if filename.endswith(".mp3") else
                "application/pdf" if filename.endswith(".pdf") else "application/zip")
        resp = send_file(io.BytesIO(data), mimetype=mime, download_name=filename,
                         as_attachment=not filename.endswith(".mp3"), conditional=True)
        resp.headers["Cache-Control"] = "private, no-store"
        resp.headers["X-Content-Type-Options"] = "nosniff"
        return resp

    def _admin_allowed():
        secret = os.getenv("NIJA_COURSE_UPLOAD_SECRET", "")
        got = request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
        return len(secret) >= 32 and hmac.compare_digest(secret, got)

    @portal.get("/admin/")
    def admin_home():
        # Credential is entered only in this browser and never stored in cookies or URLs.
        return _layout("Private Course Package Upload", '''
        <div class="card"><p>Operator only. Select the original validated NIJA
        Foundations customer ZIP, then enter the private upload token
        configured on Render. Neither token nor archive is made public.</p>
        <p><input id="archive" type="file" accept=".zip"></p>
        <p><input id="operator-token" type="password" autocomplete="off"
        placeholder="Private upload token"></p>
        <button type="button" id="import-button">Upload Protected Package</button>
        <pre id="import-result" role="status"></pre></div>
        <script>
        document.getElementById("import-button").addEventListener("click",async()=>{
          const f=document.getElementById("archive").files[0];
          const input=document.getElementById("operator-token");
          const output=document.getElementById("import-result");
          if(!f||!input.value){output.textContent="Select a ZIP and enter your token.";return;}
          const form=new FormData();form.append("package",f);
          const button=document.getElementById("import-button");button.disabled=true;
          output.textContent="Uploading and verifying private files…";
          try {
            const res=await fetch("/course-portal/admin/import",{method:"POST",
              headers:{"Authorization":"Bearer "+input.value},
              credentials:"same-origin",body:form});
            const result=await res.json();
            output.textContent=res.ok
              ? "Verified: "+result.files+" files. SHA-256: "+result.bundle_sha256
              : "Upload rejected: "+(result.error||res.status);
          } catch(e) {output.textContent="Upload failed. Retry safely.";}
          input.value="";button.disabled=false;
        });
        </script>
        ''')

    @portal.post("/admin/import")
    def admin_import():
        if not _admin_allowed():
            return jsonify({"error": "unauthorized"}), 403
        if request.content_length is None or request.content_length > MAX_ZIP + 1024 * 1024:
            return jsonify({"error": "invalid_size"}), 413
        package = request.files.get("package")
        if not package:
            return jsonify({"error": "package_required"}), 400
        payload = package.stream.read(MAX_ZIP + 1)
        try:
            digest = validate_bundle(payload)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 422
        store.import_bundle(payload, digest)
        # Flush pre-existing paid orders after the private package is available.
        # Failed emails remain durable for subsequent admin retry or buyer recovery.
        attempted = 0
        if _email_ready(current_app):
            for item in store.pending(10):
                _dispatch_one(item["session_id"], item["email"])
                attempted += 1
        return jsonify({"uploaded": True, "files": len(ALLOWED),
                        "bundle_sha256": digest, "queued_attempted": attempted})

    @portal.post("/admin/retry")
    def admin_retry():
        if not _admin_allowed():
            return jsonify({"error": "unauthorized"}), 403
        count = 0
        for job in store.pending(10):
            _dispatch_one(job["session_id"], job["email"])
            count += 1
        return jsonify({"attempted": count})

    @portal.get("/admin/preview")
    def admin_preview():
        if not _admin_allowed():
            return jsonify({"error": "unauthorized"}), 403
        # A reconciliation preview never changes entitlements or sends email.
        try:
            sessions = _stripe().checkout.Session.list(payment_link=COURSE_LINK, limit=100)
            data = sessions.get("data", [])
        except Exception:
            return jsonify({"error": "stripe_history_unavailable"}), 503
        history = {"paid": 0, "pending_or_unpaid": 0, "already_reconciled": 0,
                   "paid_without_entitlement": 0}
        ledger = current_app.config["COURSE_LEDGER"]
        for session in data:
            sid = session.get("id")
            paid = session.get("payment_status") == "paid" and session.get("status") == "complete"
            if paid:
                history["paid"] += 1
                recorded = ledger.get(sid)
                if recorded and recorded["granted"]:
                    history["already_reconciled"] += 1
                else:
                    history["paid_without_entitlement"] += 1
            else:
                history["pending_or_unpaid"] += 1
        return jsonify({"counts": history, "has_more": bool(sessions.get("has_more")),
                        "dry_run": True})

    @portal.post("/admin/reconcile")
    def admin_reconcile():
        if not _admin_allowed():
            return jsonify({"error": "unauthorized"}), 403
        sid = (request.get_json(silent=True) or {}).get("session_id", "")
        if not isinstance(sid, str) or not sid.startswith("cs_") or len(sid) > 128:
            return jsonify({"error": "valid_session_id_required"}), 400
        try:
            result = reconcile_session(_stripe(), current_app.config["COURSE_LEDGER"], sid)
        except Exception:
            log.exception("Course order reconciliation failed")
            return jsonify({"error": "provider_reconciliation_failed"}), 503
        if not result or not result["paid"]:
            return jsonify({"verified": False, "access_granted": False}), 409
        on_course_payment(current_app, sid)
        return jsonify({"verified": True, "access_granted": True,
                        "email_delivery_queued": True})

    @portal.after_request
    def secure_headers(resp):
        resp.headers.setdefault("Cache-Control", "private, no-store")
        resp.headers["Referrer-Policy"] = "no-referrer"
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["X-Frame-Options"] = "DENY"
        return resp

    @portal.get("/readyz")
    def readyz():
        return jsonify({"service": "nija-course", "ready": bool(_email_ready(current_app)),
            "access_ready": bool(_enabled(current_app)),
            "assets_present": store.has_bundle(), "email_configured": bool(os.getenv("RESEND_API_KEY")),
            "access_key_configured": bool(_signer()), "checkout_access_enabled": False}), 200

    app.register_blueprint(portal)
    return store
