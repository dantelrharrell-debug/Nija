"""Deterministic hosted payment protections; no network calls or real keys."""
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from unittest.mock import Mock

import pytest
from flask import Flask, request

import nija_game_hosted_routes as routes
from nija_game_billing import BILLING_ORIGIN, cookie_name, create_checkout, decode_attempt
from nija_game_checkout_store import CheckoutDenied, CheckoutStore, OWNER_COOKIE, client_identity

ATTEMPT = "l,20,2;s,20,2;w,0,0;w,0,0;l,20,2"
ORIGIN = "https://game.nijaaitrading.com"
SID = "cs_live_0123456789ABCDEFGHIJKLMNOP"  # pragma: allowlist secret -- synthetic checkout ID
URL = "https://checkout.stripe.com/c/pay/fixture"
OWNER = "a" * 64


@pytest.fixture
def setup(tmp_path, monkeypatch):
    tmp_path.chmod(0o700)
    path = tmp_path / "checkout.sqlite3"
    path.touch(mode=0o600)
    monkeypatch.setenv("NIJA_GAME_BROWSER_CHECKOUT_ENABLED", "true")
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_live_fixture")
    monkeypatch.setenv("NIJA_GAME_INGRESS_MODE", "direct")
    monkeypatch.setenv("NIJA_GAME_CHECKOUT_DATABASE", str(path))
    monkeypatch.setenv("NIJA_GAME_CHECKOUT_MOUNT", str(tmp_path))
    monkeypatch.setattr("nija_game_checkout_store.ismount", lambda p: str(p) == str(tmp_path))
    app = Flask(__name__)
    routes.register_hosted_routes(app)
    stripe = Mock()
    monkeypatch.setattr(routes, "stripe_client", lambda: stripe)
    provider = Mock(side_effect=lambda *a, **k: (URL, k["proof"], SID))
    monkeypatch.setattr(routes, "create_checkout", provider)
    return app, CheckoutStore(str(path)), provider


def submit(client, attempt=ATTEMPT, origin=ORIGIN, **kwargs):
    return client.post("/game/checkout/start", base_url=BILLING_ORIGIN,
                       headers={"Origin": origin}, data={"adult": "yes", "attempt": attempt}, **kwargs)


def buyer(app):
    client = app.test_client()
    client.set_cookie(OWNER_COOKIE, OWNER, domain="nija-billing-api.onrender.com")
    return client


def test_bootstrap_before_provider_and_same_site_confirmation(setup):
    app, store, provider = setup
    client = app.test_client()
    first = submit(client)
    assert first.status_code == 200
    assert b"Continue to secure checkout" in first.data
    assert "Secure" in first.headers["Set-Cookie"]
    provider.assert_not_called()
    assert submit(client, origin=BILLING_ORIGIN).status_code == 303
    assert submit(client).status_code == 303
    assert provider.call_count == 1


def test_repeated_submissions_restart_and_lost_redirect_reuse_session_and_proof(setup):
    app, store, provider = setup
    first = submit(buyer(app))
    for _ in range(5):
        result = submit(buyer(app))
        assert result.status_code == 303
        assert result.headers["Location"] == first.headers["Location"]
        assert result.headers["Set-Cookie"] == first.headers["Set-Cookie"]
    assert provider.call_count == 1
    # A new DB connection and app registration retain the same reservation.
    restarted = Flask("restarted")
    routes.register_hosted_routes(restarted)
    assert submit(buyer(restarted)).status_code == 303
    assert provider.call_count == 1


def test_simultaneous_requests_single_provider_call(setup):
    app, store, provider = setup
    entered, release = Event(), Event()

    def slow(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return URL, kwargs["proof"], SID

    provider.side_effect = slow
    with ThreadPoolExecutor(2) as pool:
        first = pool.submit(submit, buyer(app))
        assert entered.wait(5)
        second = submit(buyer(app))
        assert second.status_code == 409
        assert second.json["error"] == "checkout_in_progress"
        release.set()
        assert first.result(5).status_code == 303
    assert provider.call_count == 1


def test_lost_provider_response_retries_same_key_proof_and_parameters(setup):
    app, store, provider = setup
    provider.side_effect = TimeoutError("ambiguous fixture")
    assert submit(buyer(app)).status_code == 503
    first = provider.call_args
    assert submit(buyer(app)).status_code == 409
    with store.db() as db:
        db.execute("UPDATE checkout_reservations SET lease=0")
    provider.side_effect = lambda *a, **k: (URL, k["proof"], SID)
    assert submit(buyer(app)).status_code == 303
    assert provider.call_args == first
    assert provider.call_count == 2


def test_ambiguous_attempt_never_recreated_after_retention_window(setup):
    app, store, provider = setup
    provider.side_effect = TimeoutError()
    assert submit(buyer(app)).status_code == 503
    with store.db() as db:
        db.execute("UPDATE checkout_reservations SET created=created-86400,lease=0")
    assert submit(buyer(app)).status_code == 409
    assert provider.call_count == 1


def test_per_attempt_call_budget(setup):
    app, store, provider = setup
    provider.side_effect = TimeoutError()
    for _ in range(3):
        assert submit(buyer(app)).status_code == 503
        with store.db() as db:
            db.execute("UPDATE checkout_reservations SET lease=0")
    assert submit(buyer(app)).status_code == 409
    assert provider.call_count == 3


def test_quota_survives_cookie_rotation_and_process_restart(setup):
    app, store, provider = setup
    for i in range(10):
        store.reserve(f"owner-{i}", ATTEMPT, ORIGIN, "192.0.2.1")
    restarted = CheckoutStore(store.path)
    with pytest.raises(CheckoutDenied) as error:
        restarted.reserve("new-owner", ATTEMPT, ORIGIN, "192.0.2.1")
    assert error.value.status == 429
    assert restarted.reserve("new-owner", ATTEMPT, ORIGIN, "192.0.2.2")
    provider.assert_not_called()


def test_request_and_global_limits_bound_bootstrap_and_provider(setup):
    app, store, provider = setup
    for _ in range(30):
        assert submit(app.test_client()).status_code == 200
    assert submit(app.test_client()).status_code == 429
    provider.assert_not_called()
    # Global provider budget also applies to rotating owners and client identities.
    for i in range(100):
        store.reserve(f"owner-{i}", ATTEMPT, ORIGIN, f"192.0.2.{i}")
    with pytest.raises(CheckoutDenied) as error:
        store.reserve("another", ATTEMPT, ORIGIN, "192.0.2.200")
    assert error.value.status == 429


def test_invalid_storage_or_ingress_blocks_provider(setup, monkeypatch):
    app, store, provider = setup
    monkeypatch.delenv("NIJA_GAME_INGRESS_MODE")
    assert submit(buyer(app)).status_code == 503
    monkeypatch.setenv("NIJA_GAME_INGRESS_MODE", "direct")
    monkeypatch.setenv("NIJA_GAME_CHECKOUT_DATABASE", "/tmp/nonexistent-checkout-file")
    assert submit(buyer(app)).status_code == 503
    provider.assert_not_called()


def test_proxy_policy_rejects_spoofing_and_separates_visitors(setup, monkeypatch):
    app, _, _ = setup
    monkeypatch.setenv("NIJA_GAME_INGRESS_MODE", "proxy")
    monkeypatch.setenv("NIJA_GAME_TRUSTED_PROXY_CIDRS", "10.0.0.0/24")
    def identify(peer, forwarded):
        with app.test_request_context(environ_base={"REMOTE_ADDR": peer}, headers={"X-Forwarded-For": forwarded}):
            return client_identity(request)
    assert identify("10.0.0.2", "192.0.2.1") != identify("10.0.0.2", "192.0.2.2")
    for peer, forwarded in [("192.0.2.1", "192.0.2.2"), ("10.0.0.2", "192.0.2.1, 192.0.2.2"), ("10.0.0.2", "")]:
        with pytest.raises(CheckoutDenied):
            identify(peer, forwarded)
    monkeypatch.setenv("NIJA_GAME_INGRESS_MODE", "direct")
    assert identify("192.0.2.1", "192.0.2.200") == "192.0.2.1"


def test_legacy_and_current_report_credentials_survive_checkout_disable(setup, monkeypatch):
    app, _, provider = setup
    monkeypatch.setenv("NIJA_GAME_BROWSER_CHECKOUT_ENABLED", "false")
    # Run real entitlement checks against a provider fixture from the existing billing suite.
    from test_nija_game_billing import FakeStripe
    stripe = FakeStripe()
    url, proof, sid = create_checkout(stripe, decode_attempt(ATTEMPT), ORIGIN)
    stripe.session["metadata"]["proof_sha256"] = stripe.recorded["metadata"]["proof_sha256"]
    monkeypatch.setattr(routes, "stripe_client", lambda: stripe)
    for name in (cookie_name(sid), "__Host-nija-report"):
        client = app.test_client()
        client.set_cookie(name, proof, domain="nija-billing-api.onrender.com")
        response = client.get("/game/results?session_id=" + sid, base_url=BILLING_ORIGIN)
        assert response.status_code == 200
        stripe.session["payment_intent"]["latest_charge"]["refunded"] = True
        assert client.get("/game/results?session_id=" + sid, base_url=BILLING_ORIGIN).status_code == 403
        stripe.session["payment_intent"]["latest_charge"]["refunded"] = False
    assert app.test_client().get("/game/results?session_id=" + sid, base_url=BILLING_ORIGIN).status_code == 403
    provider.assert_not_called()


def test_real_adapter_replays_provider_session_after_lost_response(setup, monkeypatch):
    app, store, _ = setup
    from test_nija_game_billing import FakeStripe
    stripe = FakeStripe()
    sessions, calls = {}, []
    original = stripe._create

    def idempotent_create(**params):
        calls.append(params)
        key = params["idempotency_key"]
        if key not in sessions:
            sessions[key] = original(**params)
            raise TimeoutError("provider created session but response lost")
        return sessions[key]

    stripe._create = idempotent_create
    monkeypatch.setattr(routes, "stripe_client", lambda: stripe)
    monkeypatch.setattr(routes, "create_checkout", create_checkout)
    assert submit(buyer(app)).status_code == 503
    with store.db() as db:
        db.execute("UPDATE checkout_reservations SET lease=0")
    assert submit(buyer(app)).status_code == 303
    assert len(sessions) == 1
    assert len(calls) == 2 and calls[0] == calls[1]
    assert calls[0]["idempotency_key"].startswith("nija-hosted-v1-")


def test_owner_quota_and_expired_session_never_replaced(setup):
    app, store, provider = setup
    for i in range(5):
        store.reserve(OWNER, f"attempt-{i}", ORIGIN, f"client-{i}")
    with pytest.raises(CheckoutDenied) as error:
        store.reserve(OWNER, "attempt-six", ORIGIN, "different-client")
    assert error.value.status == 429
    provider.assert_not_called()
    # A cached checkout (even canceled/expired) is never automatically replaced.
    existing = store.reserve("other-owner", ATTEMPT, ORIGIN, "other-client")
    store.finish(existing["id"], URL, SID)
    with store.db() as db:
        db.execute("UPDATE checkout_reservations SET created=0 WHERE id=?", (existing["id"],))
    assert store.reserve("other-owner", ATTEMPT, ORIGIN, "other-client")["session"] == SID


def test_report_does_not_depend_on_checkout_storage_or_ingress(setup, monkeypatch):
    app, _, _ = setup
    from test_nija_game_billing import FakeStripe, BROWSER_PROOF, SESSION_ID
    monkeypatch.setattr(routes, "stripe_client", lambda: FakeStripe())
    monkeypatch.delenv("NIJA_GAME_CHECKOUT_DATABASE")
    monkeypatch.delenv("NIJA_GAME_INGRESS_MODE")
    client = app.test_client()
    client.set_cookie("__Host-nija-report", BROWSER_PROOF, domain="nija-billing-api.onrender.com")
    assert client.get("/game/results?session_id=" + SESSION_ID, base_url=BILLING_ORIGIN).status_code == 200


def test_nonmounted_or_public_storage_denies_checkout(setup, monkeypatch):
    app, store, provider = setup
    monkeypatch.setattr("nija_game_checkout_store.ismount", lambda p: False)
    assert submit(buyer(app)).status_code == 503
    provider.assert_not_called()


@pytest.mark.parametrize("origin", ["null", "", "https://attacker.example",
                                    BILLING_ORIGIN + ".attacker.example",
                                    "http://nija-billing-api.onrender.com"])
def test_untrusted_origins_remain_denied_with_owner_cookie(setup, origin):
    app, _, provider = setup
    result = submit(buyer(app), origin=origin)
    assert result.status_code == 403
    assert result.json["error"] == "origin_not_allowed"
    provider.assert_not_called()


def test_confirmation_policy_is_narrow_and_reports_keep_no_referrer(setup):
    app, _, provider = setup
    result = submit(app.test_client())
    assert result.headers["Referrer-Policy"] == "same-origin"
    directives = result.headers["Content-Security-Policy"].split("; ")
    assert "form-action 'self' https://checkout.stripe.com https://*.checkout.stripe.com" in directives
    assert "default-src 'none'" in directives
    assert "base-uri 'none'" in directives
    for path in ("/game/cancelled", "/game/results?session_id=" + SID):
        report = app.test_client().get(path, base_url=BILLING_ORIGIN)
        assert report.headers["Referrer-Policy"] == "no-referrer"
        assert report.headers["Content-Security-Policy"].endswith("form-action 'self'")
    provider.assert_not_called()


@pytest.mark.parametrize("kind", ["traversal", "nested_traversal", "prefix_sibling",
                                  "file_symlink", "directory_symlink", "mount_traversal",
                                  "mount_symlink", "relative", "missing", "public"])
def test_storage_escape_denied_before_database_open(setup, monkeypatch, tmp_path, kind):
    from pathlib import Path
    app, store, provider = setup
    mount = Path(store.path).parent
    outside = mount.parent / (mount.name + "-outside")
    outside.mkdir(mode=0o700)
    target = outside / "journal.sqlite3"
    target.touch(mode=0o600)
    path = target
    if kind == "traversal":
        path = mount / ".." / outside.name / target.name
    elif kind == "nested_traversal":
        (mount / "nested").mkdir(mode=0o700)
        path = mount / "nested" / ".." / ".." / outside.name / target.name
    elif kind == "file_symlink":
        path = mount / "link.sqlite3"
        path.symlink_to(target)
    elif kind == "directory_symlink":
        (mount / "link").symlink_to(outside, target_is_directory=True)
        path = mount / "link" / target.name
    elif kind == "mount_traversal":
        monkeypatch.setenv("NIJA_GAME_CHECKOUT_MOUNT", str(mount / ".." / mount.name))
        path = Path(store.path)
    elif kind == "mount_symlink":
        link = outside / "mount-link"
        link.symlink_to(mount, target_is_directory=True)
        monkeypatch.setenv("NIJA_GAME_CHECKOUT_MOUNT", str(link))
        path = link / Path(store.path).name
    elif kind == "relative":
        path = Path("checkout.sqlite3")
    elif kind == "missing":
        path = mount / "missing.sqlite3"
    elif kind == "public":
        path = Path(store.path)
        path.chmod(0o644)
    monkeypatch.setenv("NIJA_GAME_CHECKOUT_DATABASE", str(path))
    connect = Mock(side_effect=AssertionError("unsafe SQLite open"))
    monkeypatch.setattr("nija_game_checkout_store.sqlite3.connect", connect)
    assert submit(buyer(app)).status_code == 503
    connect.assert_not_called()
    provider.assert_not_called()
    assert target.read_bytes() == b""


def test_private_nested_journal_survives_real_process_restart(setup, monkeypatch):
    import json
    import os
    from pathlib import Path
    import subprocess
    import sys
    _, store, _ = setup
    mount = Path(store.path).parent
    (mount / "nested").mkdir(mode=0o700)
    path = mount / "nested" / "checkout.sqlite3"
    path.touch(mode=0o600)
    store = CheckoutStore(str(path))
    row = store.reserve(OWNER, ATTEMPT, BILLING_ORIGIN, "192.0.2.1")
    store.finish(row["id"], URL, SID)
    # New interpreter, no inherited connection or in-memory reservation. Only the
    # mount detection is simulated; containment, permissions and SQLite are real.
    script = '''
import json, os
import nija_game_checkout_store as module
module.ismount = lambda p: str(p) == os.environ["NIJA_GAME_CHECKOUT_MOUNT"]
store = module.CheckoutStore(os.environ["RESTART_JOURNAL"])
row = store.reserve("a" * 64, os.environ["RESTART_ATTEMPT"], os.environ["RESTART_ORIGIN"], "192.0.2.1")
print(json.dumps(row))
'''
    result = subprocess.run([sys.executable, "-c", script], check=True, capture_output=True, text=True,
                            env={**os.environ, "RESTART_JOURNAL": str(path),
                                 "RESTART_ATTEMPT": ATTEMPT, "RESTART_ORIGIN": BILLING_ORIGIN})
    restored = json.loads(result.stdout)
    assert (restored["id"], restored["proof"], restored["url"], restored["session"], restored["calls"]) == (
        row["id"], row["proof"], URL, SID, 1)


def test_browser_confirmation_redirect_and_replay(setup, monkeypatch):
    """Real browser policies and cookies; Stripe and HTTPS responses are intercepted."""
    import os
    from playwright.sync_api import sync_playwright
    from urllib.parse import urlsplit
    from test_nija_game_billing import FakeStripe
    app, _, _ = setup
    stripe = FakeStripe()
    provider = Mock(wraps=stripe._create)
    stripe._create = provider
    monkeypatch.setattr(routes, "stripe_client", lambda: stripe)
    monkeypatch.setattr(routes, "create_checkout", create_checkout)
    import base64
    posts, stripe_gets = [], []
    http = app.test_client(use_cookies=False)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=os.getenv("NIJA_TEST_CHROMIUM"))
        context = browser.new_context(service_workers="block")
        page = context.new_page()
        # Playwright route() only intercepts the first URL in a redirect chain.
        # CDP Fetch intercepts every hop, including the 303 target: no Stripe I/O.
        cdp = context.new_cdp_session(page)

        def serve(event):
            req = event["request"]
            parsed = urlsplit(req["url"])
            headers = {k.lower(): v for k, v in req["headers"].items()}
            status, response_headers = 200, {"Content-Type": "text/html"}
            if parsed.netloc in ("game.nijaaitrading.com", "attacker.example"):
                body = ('<form method="post" action="' + BILLING_ORIGIN + '/game/checkout/start">'
                        '<input name="adult" value="yes"><input name="attempt" value="' + ATTEMPT + '">'
                        '<button>Optional report</button></form>').encode()
            elif parsed.netloc == "nija-billing-api.onrender.com":
                if req["method"] == "POST":
                    posts.append(headers)
                result = http.open(req["url"], method=req["method"], headers=headers, data=req.get("postData"))
                status, response_headers, body = result.status_code, dict(result.headers), result.data
            elif parsed.netloc == "checkout.stripe.com":
                stripe_gets.append(headers)
                body = b"<title>Stripe fixture</title>"
            else:
                # Fail closed without ever continuing an unexpected network call.
                cdp.send("Fetch.failRequest", {"requestId": event["requestId"], "errorReason": "BlockedByClient"})
                raise AssertionError("Unexpected browser request: " + req["url"])
            cdp.send("Fetch.fulfillRequest", {
                "requestId": event["requestId"], "responseCode": status,
                "responseHeaders": [{"name": k, "value": v} for k, v in response_headers.items()],
                "body": base64.b64encode(body).decode(),
            })

        cdp.on("Fetch.requestPaused", serve)
        cdp.send("Fetch.enable", {"patterns": [{"urlPattern": "*"}]})
        page.goto(ORIGIN)
        page.get_by_role("button", name="Optional report").click()
        page.get_by_role("button", name="Continue to secure checkout — $1").click()
        page.wait_for_url("https://checkout.stripe.com/**")
        assert posts[0]["origin"] == ORIGIN
        assert posts[1]["origin"] == BILLING_ORIGIN
        assert "referer" not in stripe_gets[0]
        assert provider.call_count == 1
        # Browser-owned resubmission after returning to the free game reuses the
        # same session and receipt, without a second provider session creation.
        page.goto(ORIGIN)
        page.get_by_role("button", name="Optional report").click()
        page.wait_for_url("https://checkout.stripe.com/**")
        assert provider.call_count == 1
        assert len(stripe_gets) == 2
        assert any(c["name"] == cookie_name(SID) for c in context.cookies(BILLING_ORIGIN))
        page.goto("https://attacker.example")
        page.get_by_role("button", name="Optional report").click()
        assert "origin_not_allowed" in page.content()
        assert posts[-1]["origin"] == "https://attacker.example"
        assert provider.call_count == 1 and len(stripe_gets) == 2
        browser.close()
