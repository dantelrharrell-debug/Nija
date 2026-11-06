"""HTTP tests for the same-origin return UI; never a second payment service."""
from game_sandbox.app import create_app
from test_game_sandbox import setup, fulfill, signed  # noqa: F401 - pytest fixture
from game_sandbox.service import COOKIE


def test_return_page_never_grants_report_from_url(setup):
    service, stripe, run, *_ = setup
    client = create_app(service).test_client()
    response = client.get('/report?run_id=' + run + '&paid=true', base_url=service.config.origin)
    assert response.status_code == 200
    assert b'Checking report access' in response.data
    assert b'test checkout' not in response.data
    assert response.headers['Cache-Control'] == 'no-store'
    assert "script-src 'self'" in response.headers['Content-Security-Policy']
    assert client.get('/sandbox/runs/' + run + '/report').status_code == 403
    assert stripe.calls == 0


def test_browser_module_allowlist_excludes_server_and_private_files(setup):
    client = create_app(setup[0]).test_client()
    for name in ['client.mjs', 'preview-controller.mjs', 'preview-panel.mjs', 'recovery.mjs']:
        response = client.get('/sandbox-ui/' + name)
        assert response.status_code == 200
        assert response.mimetype == 'text/javascript'
    for name in ['service.py', 'app.py', 'trading_iq_sandbox.sqlite3', '../service.py']:
        assert client.get('/sandbox-ui/' + name).status_code == 404


def test_returning_owner_and_replay_refund_use_existing_protection(setup):
    service, stripe, run, owner, *_ = setup
    sid = fulfill(setup)
    app = create_app(service)
    buyer = app.test_client()
    buyer.set_cookie(COOKIE, owner, domain='staging.example', secure=True)
    headers = {'Origin': service.config.origin}
    url = '/sandbox/runs/' + run
    assert buyer.post(url + '/resume', base_url=service.config.origin, headers=headers, json={}).status_code == 200
    assert buyer.get(url + '/report', base_url=service.config.origin).status_code == 200
    stranger = app.test_client()
    assert stranger.get(url + '/report', base_url=service.config.origin).status_code == 403
    stripe.sessions[sid]['payment_intent']['latest_charge']['refunded'] = True
    assert buyer.get(url + '/report', base_url=service.config.origin).status_code == 403
    # Replay a paid event after fresh refund detection must not restore access.
    service.webhook(*signed(service.config, 'checkout.session.completed', stripe.sessions[sid]))
    assert buyer.get(url + '/report', base_url=service.config.origin).status_code == 403
    assert stripe.calls == 1
