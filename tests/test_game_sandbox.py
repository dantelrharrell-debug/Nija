"""Sandbox boundary integration tests. Fixtures are NOT the canonical IONOS game."""

import concurrent.futures
import copy
import hashlib
import hmac
import json
import secrets
import sqlite3
import time
from dataclasses import replace

import pytest

from game_sandbox.app import StripeGateway, create_app
from game_sandbox.service import COOKIE, Config, Denied, Manifest, Sandbox


class FakeStripe(StripeGateway):
    """Simulate provider state but use the real Stripe SDK signature verifier."""

    def __init__(self, config):
        super().__init__(config.key)
        self.config, self.sessions, self.keys, self.calls = config, {}, {}, 0
        self.fail_after_create = False
        self.bad_price = False

    def price(self, price_id):
        return dict(
            id=price_id,
            product=self.config.product,
            unit_amount=99 if self.bad_price else 100,
            active=True,
            livemode=False,
            type="one_time",
            currency="usd",
        )

    def create(self, params, idempotency_key):
        self.calls += 1
        if idempotency_key not in self.keys:
            sid = "cs_test_" + secrets.token_hex(16)
            self.keys[idempotency_key] = sid
            self.sessions[sid] = dict(
                copy.deepcopy(params),
                id=sid,
                livemode=False,
                url="https://checkout.stripe.com/c/pay/" + sid,
                status="open",
                payment_status="unpaid",
                amount_total=100,
                currency="usd",
            )
        if self.fail_after_create:
            self.fail_after_create = False
            raise ConnectionError("simulated lost response")
        return copy.deepcopy(self.sessions[self.keys[idempotency_key]])

    def purchase(self, session_id):
        return copy.deepcopy(self.sessions[session_id]), {
            "has_more": False,
            "data": [
                dict(
                    quantity=1,
                    amount_total=100,
                    currency="usd",
                    price=dict(id=self.config.price, product=self.config.product),
                )
            ],
        }

    def pay(self, sid):
        session = self.sessions[sid]
        # Stripe returns only metadata set on the session, not request-only fields.
        session.update(
            status="complete",
            payment_status="paid",
            payment_intent={
                "id": "pi_" + secrets.token_hex(12),
                "status": "succeeded",
                "amount_received": 100,
                "currency": "usd",
                "livemode": False,
                "latest_charge": {
                    "paid": True,
                    "livemode": False,
                    "refunded": False,
                    "disputed": False,
                    "amount_refunded": 0,
                    "status": "succeeded",
                },
            },
        )


def fixture_manifest(total=12):
    return Manifest(
        dict(
            version="fixture-not-ionos-v1",
            source_sha256="a" * 64,
            structure="12_total" if total == 12 else "12_per_challenge",
            challenges=[
                {"rounds": [{"id": f"round_{i}_{j}", "choices": 3} for j in range(12)]} for i in range(total // 12)
            ],
        )
    )


@pytest.fixture
def setup(tmp_path):
    config = Config(
        str(tmp_path / "trading_iq_sandbox.sqlite3"),
        "https://staging.example",
        "rk_test_" + secrets.token_hex(24),
        "whsec_" + secrets.token_hex(24),
        "price_sandbox_fixture",
        "prod_sandbox_fixture",
        True,
    )
    manifest, stripe = fixture_manifest(), FakeStripe(config)
    received = []

    def report(answers):
        received.append(answers)
        return {"fixture": True, "decisions": answers}

    service = Sandbox(config, manifest, stripe, report)
    run, owner, csrf = service.start(True)
    answers = [{"roundId": row["id"], "choice": index % 3} for index, row in enumerate(manifest.rounds)]
    service.complete(run, owner, csrf, answers)
    return service, stripe, run, owner, csrf, answers, received


def signed(config, kind, obj, event_id=None, timestamp=None, live=False):
    raw = json.dumps(
        {
            "id": event_id or "evt_" + secrets.token_hex(12),
            "object": "event",
            "livemode": live,
            "type": kind,
            "data": {"object": obj},
        }
    ).encode()
    stamp = int(time.time()) if timestamp is None else timestamp
    signature = hmac.new(config.webhook_secret.encode(), str(stamp).encode() + b"." + raw, hashlib.sha256).hexdigest()
    return raw, f"t={stamp},v1={signature}"


def paid(setup):
    service, stripe, run, owner, csrf, *_ = setup
    service.checkout(run, owner, csrf)
    sid = next(iter(stripe.sessions))
    stripe.pay(sid)
    return sid


def fulfill(setup):
    sid = paid(setup)
    service, stripe, *_ = setup
    service.webhook(*signed(service.config, "checkout.session.completed", stripe.sessions[sid]))
    return sid


def test_free_game_and_existing_paths_untouched(setup):
    service, stripe, *_ = setup
    assert stripe.calls == 0  # Complete without checkout; report builder not invoked.
    app = create_app(service).test_client()
    assert app.get("/api/game/checkout").status_code == 404
    assert app.get("/sandbox/health").json["live_payments"] is False


@pytest.mark.parametrize(
    "key,enabled",
    [("rk_live_placeholder", True), ("sk_live_placeholder", True), ("", True), ("rk_test_placeholder", False)],
)
def test_production_credentials_and_default_off_rejected(setup, key, enabled):
    config = replace(setup[0].config, key=key, enabled=enabled)
    with pytest.raises(Denied):
        config.validate()


def test_only_separate_database(setup):
    with pytest.raises(Denied):
        replace(setup[0].config, database="/tmp/customer.sqlite3").validate()


@pytest.mark.parametrize("total", [12, 72])
def test_explicit_structure_no_five_or_six_decision_reuse(total):
    manifest = fixture_manifest(total)
    assert len(manifest.rounds) == total
    with pytest.raises(Denied):
        manifest.answers([{"roundId": "round_0_0", "choice": 1}] * (total - 1))


def test_youth_and_forged_age_rejected_without_persisting(setup):
    service = setup[0]
    for age in (False, None, "true", 1, 17):
        with pytest.raises(Denied):
            service.start(age)
    with service.db() as db:
        assert db.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 1


def test_exact_history_and_immutability(setup):
    service, _, run, owner, csrf, answers, _ = setup
    service.complete(run, owner, csrf, answers)
    for altered in (
        answers[::-1],
        answers[:5],
        [dict(answers[0], score=100)] + answers[1:],
        [dict(answers[0], choice=True)] + answers[1:],
    ):
        with pytest.raises(Denied):
            service.complete(run, owner, csrf, altered)
    altered = copy.deepcopy(answers)
    altered[0]["choice"] = 2
    with pytest.raises(Denied, match="immutable"):
        service.complete(run, owner, csrf, altered)


def test_owner_csrf_and_origin_boundaries(setup):
    service, stripe, run, owner, csrf, *_ = setup
    with pytest.raises(Denied):
        service.checkout(run, "b" * 64, csrf)
    with pytest.raises(Denied):
        service.checkout(run, owner, "b" * 64)
    client = create_app(service).test_client()
    for origin in (None, "https://evil.example"):
        assert (
            client.post(
                "/sandbox/runs", json={"adultConfirmed": True}, headers={"Origin": origin} if origin else {}
            ).status_code
            == 403
        )
    assert stripe.calls == 0


def test_one_dollar_price_and_one_checkout_per_run(setup):
    service, stripe, run, owner, csrf, *_ = setup
    first = service.checkout(run, owner, csrf)
    second = service.checkout(run, owner, csrf)
    assert first["url"] == second["url"] and stripe.calls == 1
    session = next(iter(stripe.sessions.values()))
    assert session["mode"] == "payment"
    assert session["line_items"] == [{"price": service.config.price, "quantity": 1}]
    assert "payment_method_types" not in session
    assert "answers" not in session["metadata"]
    assert owner not in json.dumps(session)


def test_bad_price_rejected_before_charge(setup):
    service, stripe, run, owner, csrf, *_ = setup
    stripe.bad_price = True
    with pytest.raises(Denied):
        service.checkout(run, owner, csrf)
    assert stripe.calls == 0


def test_lost_stripe_response_reuses_idempotency_key(setup):
    service, stripe, run, owner, csrf, *_ = setup
    stripe.fail_after_create = True
    with pytest.raises(ConnectionError):
        service.checkout(run, owner, csrf)
    service.checkout(run, owner, csrf)
    assert len(stripe.sessions) == 1 and stripe.calls == 2


def test_ambiguous_attempt_not_recreated_after_stripe_window(setup):
    service, stripe, run, owner, csrf, *_ = setup
    stripe.fail_after_create = True
    with pytest.raises(ConnectionError):
        service.checkout(run, owner, csrf)
    with service.db() as db:
        db.execute("UPDATE checkouts SET started=0")
    with pytest.raises(Denied, match="reconciliation"):
        service.checkout(run, owner, csrf)
    assert len(stripe.sessions) == 1


def test_redirect_never_fulfills_and_reopen_does_not_charge(setup):
    service, stripe, run, owner, _, answers, received = setup
    sid = paid(setup)
    with pytest.raises(Denied, match="webhook"):
        service.report(run, owner)
    event = signed(service.config, "checkout.session.completed", stripe.sessions[sid])
    service.webhook(*event)
    service.webhook(*event)
    assert service.report(run, owner)["decisions"] == answers
    assert service.report(run, owner)["decisions"] == answers
    assert received == [answers, answers] and stripe.calls == 1
    with pytest.raises(Denied):
        service.report(run, "b" * 64)
    with service.db() as db:
        assert db.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 1


def test_async_payment_pending_then_success(setup):
    service, stripe, run, owner, csrf, *_ = setup
    service.checkout(run, owner, csrf)
    sid = next(iter(stripe.sessions))
    service.webhook(*signed(service.config, "checkout.session.completed", stripe.sessions[sid]))
    with pytest.raises(Denied):
        service.report(run, owner)
    stripe.pay(sid)
    service.webhook(*signed(service.config, "checkout.session.async_payment_succeeded", stripe.sessions[sid]))
    assert service.report(run, owner)["fixture"] is True


@pytest.mark.parametrize("kind", ["charge.refunded", "charge.dispute.created", "refund.created"])
def test_reversals_before_or_after_fulfillment_are_sticky(setup, kind):
    service, stripe, run, owner, *_ = setup
    sid = fulfill(setup)
    pi = stripe.sessions[sid]["payment_intent"]["id"]
    service.webhook(*signed(service.config, kind, {"payment_intent": pi}))
    service.webhook(*signed(service.config, "checkout.session.completed", stripe.sessions[sid]))
    with pytest.raises(Denied):
        service.report(run, owner)


def test_refund_before_first_completion_blocks_grant(setup):
    service, stripe, run, owner, *_ = setup
    sid = paid(setup)
    pi = stripe.sessions[sid]["payment_intent"]["id"]
    service.webhook(*signed(service.config, "charge.refunded", {"payment_intent": pi}))
    service.webhook(*signed(service.config, "checkout.session.completed", stripe.sessions[sid]))
    with pytest.raises(Denied):
        service.report(run, owner)


def test_current_provider_state_checked_even_when_webhook_delayed(setup):
    service, stripe, run, owner, *_ = setup
    sid = fulfill(setup)
    stripe.sessions[sid]["payment_intent"]["latest_charge"]["amount_refunded"] = 1
    with pytest.raises(Denied):
        service.report(run, owner)


def test_bad_signature_tamper_and_old_signature_never_fulfill(setup):
    service, stripe, run, owner, *_ = setup
    sid = paid(setup)
    raw, sig = signed(service.config, "checkout.session.completed", stripe.sessions[sid])
    for payload, signature in (
        (raw + b" ", sig),
        (raw, ""),
        signed(service.config, "checkout.session.completed", stripe.sessions[sid], timestamp=1),
    ):
        with pytest.raises(Exception):
            service.webhook(payload, signature)
    with pytest.raises(Denied):
        service.report(run, owner)


@pytest.mark.parametrize("mutation", ["live", "amount", "owner", "product", "unpaid"])
def test_invalid_receipt_cannot_fulfill(setup, mutation):
    service, stripe, run, owner, *_ = setup
    sid = paid(setup)
    session = stripe.sessions[sid]
    if mutation == "live":
        session["livemode"] = True
    elif mutation == "amount":
        session["amount_total"] = 99
    elif mutation == "owner":
        session["metadata"]["run_id"] = "other"
    elif mutation == "product":
        stripe.config = replace(stripe.config, product="prod_wrong")
    else:
        session["payment_status"] = "unpaid"
    service.webhook(*signed(service.config, "checkout.session.completed", session))
    with pytest.raises(Denied):
        service.report(run, owner)


def test_http_flow_ownership_cookie_csrf_and_reopen(setup):
    service, stripe, *_ = setup
    client = create_app(service).test_client()
    headers = {"Origin": service.config.origin}
    start = client.post("/sandbox/runs", json={"adultConfirmed": True}, headers=headers)
    cookie = start.headers["Set-Cookie"]
    assert all(part in cookie for part in ("Secure", "HttpOnly", "SameSite=Lax", "Path=/"))
    assert COOKIE in cookie
    run, csrf = start.json["run_id"], start.json["csrf"]
    prefix = "/sandbox/runs/" + run
    answers = [{"roundId": row["id"], "choice": 1} for row in service.manifest.rounds]
    headers["X-NIJA-CSRF"] = csrf
    assert client.post(prefix + "/complete", json={"answers": answers}, headers=headers).status_code == 200
    assert client.post(prefix + "/checkout", json={}, headers=headers).status_code == 200
    assert client.get(prefix + "/report").status_code == 403
    sid = next(iter(stripe.sessions))
    stripe.pay(sid)
    raw, signature = signed(service.config, "checkout.session.completed", stripe.sessions[sid])
    assert (
        client.post(
            "/sandbox/stripe/webhook",
            data=raw,
            headers={"Stripe-Signature": signature},
            content_type="application/json",
        ).status_code
        == 200
    )
    assert client.get(prefix + "/report").json["report"]["decisions"] == answers
    assert client.post(prefix + "/resume", json={}, headers=headers).json["csrf"] != csrf
    other = create_app(service).test_client()
    assert other.get(prefix + "/report").status_code == 403
    assert client.get(prefix + "/report").headers["Cache-Control"] == "no-store"


def test_backup_restart_restore(setup, tmp_path):
    service, stripe, run, owner, *_ = setup
    fulfill(setup)
    backup = str(tmp_path / "backup.sqlite3")
    service.backup(backup)
    with sqlite3.connect(backup) as db:
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert db.execute("SELECT entitled FROM checkouts").fetchone()[0] == 1
        assert owner not in str(db.execute("SELECT * FROM runs").fetchall())
    restarted = Sandbox(service.config, service.manifest, stripe, service.report_builder)
    assert restarted.report(run, owner)["fixture"] is True
    restore_dir = tmp_path / "restore"
    restore_dir.mkdir()
    restore_path = restore_dir / "trading_iq_sandbox.sqlite3"
    restore_path.write_bytes(open(backup, "rb").read())
    restored = Sandbox(
        replace(service.config, database=str(restore_path)), service.manifest, stripe, service.report_builder
    )
    assert restored.report(run, owner)["fixture"] is True


def test_sdk_adapter_uses_fixed_namespace_and_stable_key(setup):
    from types import SimpleNamespace
    import stripe
    from unittest.mock import Mock

    config = setup[0].config
    gateway = StripeGateway(config.key)
    response = stripe.StripeObject.construct_from({"id": "cs_test_mocked1234"}, None)
    create = Mock(return_value=response)
    gateway.client = SimpleNamespace(
        v1=SimpleNamespace(checkout=SimpleNamespace(sessions=SimpleNamespace(create=create)))
    )
    assert gateway.create({"mode": "payment"}, "stable-key")["id"] == "cs_test_mocked1234"
    first = create.call_args
    gateway.create({"mode": "payment"}, "stable-key")
    assert first == create.call_args
    assert create.call_args.kwargs["options"] == {"idempotency_key": "stable-key"}
    assert "integration_identifier" in create.call_args.kwargs["params"]


def test_concurrent_checkout_and_webhook_deliveries(setup):
    service, stripe, run, owner, csrf, *_ = setup
    # Real Stripe provides atomic idempotency. Bind once, then stress local duplicate requests.
    original = service.checkout(run, owner, csrf)
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: service.checkout(run, owner, csrf), range(8)))
    assert all(row["url"] == original["url"] for row in results)
    sid = next(iter(stripe.sessions))
    stripe.pay(sid)
    delivery = signed(service.config, "checkout.session.completed", stripe.sessions[sid])
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda _: service.webhook(*delivery), range(8)))
    assert service.report(run, owner)["fixture"] is True
    with service.db() as db:
        assert db.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 1


def test_provider_outage_rolls_back_event_and_report_fails_closed(setup, monkeypatch):
    service, stripe, run, owner, *_ = setup
    sid = paid(setup)
    delivery = signed(service.config, "checkout.session.completed", stripe.sessions[sid])
    with monkeypatch.context() as context:
        context.setattr(stripe, "purchase", lambda _: (_ for _ in ()).throw(ConnectionError()))
        with pytest.raises(ConnectionError):
            service.webhook(*delivery)
    with service.db() as db:
        assert db.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0
    service.webhook(*delivery)
    with monkeypatch.context() as context:
        context.setattr(stripe, "purchase", lambda _: (_ for _ in ()).throw(ConnectionError()))
        with pytest.raises(ConnectionError):
            service.report(run, owner)


def test_signature_error_is_400_and_live_event_is_rejected(setup):
    service = setup[0]
    client = create_app(service).test_client()
    assert (
        client.post("/sandbox/stripe/webhook", data=b"{}", headers={"Stripe-Signature": "invalid"}).status_code == 400
    )
    raw, signature = signed(service.config, "checkout.session.completed", {}, live=True)
    assert client.post("/sandbox/stripe/webhook", data=raw, headers={"Stripe-Signature": signature}).status_code == 400


def test_resume_never_mutates_on_cross_origin_get(setup):
    service, _, run, *_ = setup
    client = create_app(service).test_client()
    assert client.get(f"/sandbox/runs/{run}/resume").status_code == 405


def test_unbound_own_checkout_is_retried_not_lost(setup):
    service = setup[0]
    delivery = signed(
        service.config,
        "checkout.session.completed",
        {"id": "cs_test_unbound12345", "metadata": {"offer": "nija-unified-iq-sandbox-v1"}},
    )
    with pytest.raises(Denied, match="not_yet_bound"):
        service.webhook(*delivery)
    with service.db() as db:
        assert db.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0


def test_recovered_game_runs_through_owned_payment_and_existing_report(setup):
    from game_sandbox.ionos import PublishedGame, build_published_report

    old, stripe, _, _, _, _, _ = setup
    service = Sandbox(old.config, PublishedGame(), stripe, build_published_report)
    run, owner, csrf = service.start(True)
    payload = {
        "mode": "standard",
        "level": "beginner",
        "dayNum": 0,
        "challenges": [[{"action": "hold", "stop": False} for _ in range(12)] for _ in range(6)],
    }
    service.complete(run, owner, csrf, payload)
    service.checkout(run, owner, csrf)
    sid = next(iter(stripe.sessions))
    stripe.pay(sid)
    with pytest.raises(Denied, match="webhook"):
        service.report(run, owner)
    service.webhook(*signed(service.config, "checkout.session.completed", stripe.sessions[sid]))
    result = service.report(run, owner)
    assert result["report"]["tradingIQ"] == 50
    assert len(result["report"]["challenges"]) == 6
    assert sum(len(c["decisions"]) for c in result["report"]["challenges"]) == 72
    assert "<script" not in result["download_html"]
    assert service.report(run, owner) == result
    assert stripe.calls == 1


def test_published_payload_rejects_old_shapes_and_tampering():
    from game_sandbox.ionos import PublishedGame

    game = PublishedGame()
    valid = {
        "mode": "standard",
        "level": "advanced",
        "dayNum": 0,
        "challenges": [[{"action": "buy", "stop": True} for _ in range(12)] for _ in range(6)],
    }
    assert len(json.loads(game.answers(valid))["challenges"]) == 6
    for invalid in (
        [{"roundId": "round_0", "choice": 1}] * 72,
        dict(valid, score=100),
        dict(valid, dayNum=True),
        dict(valid, challenges=valid["challenges"][:1]),
        dict(valid, challenges=[[{"action": "buy", "stop": 1}] * 12] * 6),
    ):
        with pytest.raises(Denied):
            game.answers(invalid)


def test_canonical_environment_factory_needs_no_export_or_custom_adapter(setup, monkeypatch):
    from game_sandbox.app import from_environment
    from game_sandbox.ionos import PublishedGame

    config = setup[0].config
    settings = {
        "NIJA_IQ_SANDBOX_DATABASE": config.database,
        "NIJA_IQ_SANDBOX_ORIGIN": config.origin,
        "NIJA_IQ_SANDBOX_STRIPE_KEY": config.key,
        "NIJA_IQ_SANDBOX_WEBHOOK_SECRET": config.webhook_secret,
        "NIJA_IQ_SANDBOX_PRICE_ID": config.price,
        "NIJA_IQ_SANDBOX_PRODUCT_ID": config.product,
        "NIJA_IQ_SANDBOX_ENABLED": "true",
        "NIJA_IQ_SANDBOX_GAME": "published72",
        "NIJA_IQ_SANDBOX_MANIFEST_SHA256": PublishedGame().digest,
    }
    for key, value in settings.items():
        monkeypatch.setenv(key, value)
    assert from_environment().test_client().get("/sandbox/health").json["live_payments"] is False
    monkeypatch.setenv("NIJA_IQ_SANDBOX_MANIFEST_SHA256", "wrong")
    with pytest.raises(Denied, match="manifest_pin"):
        from_environment()


def test_original_report_receives_no_secrets_and_never_uses_a_shell(monkeypatch):
    from game_sandbox.ionos import build_published_report
    import subprocess
    from unittest.mock import Mock

    payload = {
        "mode": "standard",
        "level": "beginner",
        "dayNum": 0,
        "challenges": [[{"action": "hold", "stop": False} for _ in range(12)] for _ in range(6)],
    }
    response = {"report": {"challenges": [{"decisions": [{}] * 12} for _ in range(6)]}, "download_html": "safe"}
    fake = Mock(return_value=subprocess.CompletedProcess([], 0, json.dumps(response), ""))
    monkeypatch.setenv("A_PRIVATE_SECRET", "not-for-node")
    monkeypatch.setattr(subprocess, "run", fake)
    build_published_report(payload)
    assert fake.call_args.kwargs["shell"] is False
    assert set(fake.call_args.kwargs["env"]) == {"PATH"}
    assert fake.call_args.args[0][0].startswith("/")
    assert json.loads(fake.call_args.kwargs["input"]) == payload
