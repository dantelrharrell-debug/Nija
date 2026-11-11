"""Loopback-only browser acceptance of the original report and protected API.

All processor calls use FakeStripe. These checks never contact Stripe or Render.
"""
from dataclasses import replace
import secrets
import shutil
import ssl
import subprocess
import threading

import pytest
from playwright.sync_api import expect, sync_playwright
from werkzeug.serving import make_server

from game_sandbox.app import create_app
from game_sandbox.ionos import PublishedGame, build_published_report
from game_sandbox.service import Config, Sandbox
from test_game_sandbox import FakeStripe, signed


@pytest.fixture
def browser_stage(tmp_path, monkeypatch):
    """Serve the actual sandbox API and return page over private loopback TLS."""
    monkeypatch.setenv('NIJA_IQ_SANDBOX_INGRESS_MODE', 'direct')
    key, cert = tmp_path / 'key.pem', tmp_path / 'cert.pem'
    subprocess.run([
        'openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes',
        '-keyout', str(key), '-out', str(cert), '-days', '1', '-subj', '/CN=localhost',
    ], check=True, capture_output=True)
    key.chmod(0o600)
    tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    tls.load_cert_chain(cert, key)
    config = Config(
        str(tmp_path / 'trading_iq_sandbox.sqlite3'), 'https://127.0.0.1',
        'rk_test_' + secrets.token_hex(24), 'whsec_' + secrets.token_hex(24),
        'price_browser_fixture', 'prod_browser_fixture', True,
    )
    stripe = FakeStripe(config)
    service = Sandbox(config, PublishedGame(), stripe, build_published_report)
    server = make_server('127.0.0.1', 0, create_app(service), ssl_context=tls, threaded=True)
    origin = 'https://127.0.0.1:' + str(server.server_port)
    service.config = stripe.config = replace(config, origin=origin)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path=shutil.which('chromium'), headless=True,
        )
        try:
            yield browser, origin, service, stripe
        finally:
            browser.close()
            server.shutdown()
            thread.join(timeout=5)
            server.server_close()


def browser_run(context, origin: str, service: Sandbox, stripe: FakeStripe, *, paid: bool = True) -> tuple[str, str]:
    """Complete the original 72-decision payload using real same-origin HTTP."""
    headers = {'Origin': origin}
    receipt = context.request.post(origin + '/sandbox/runs', data={'adultConfirmed': True}, headers=headers)
    assert receipt.status == 200
    run = receipt.json()
    headers['X-NIJA-CSRF'] = run['csrf']
    answers = dict(mode='standard', level='beginner', dayNum=0,
                   challenges=[[dict(action='hold', stop=False) for _ in range(12)] for _ in range(6)])
    prefix = origin + '/sandbox/runs/' + run['run_id']
    assert context.request.post(prefix + '/complete', data={'answers': answers}, headers=headers).status == 200
    assert context.request.post(prefix + '/checkout', data={}, headers=headers).status == 200
    sid = next(reversed(stripe.sessions))
    if paid:
        stripe.pay(sid)
        service.webhook(*signed(service.config, 'checkout.session.completed', stripe.sessions[sid]))
    return run['run_id'], sid


@pytest.mark.parametrize('width', [375, 768, 1280])
def test_original_report_return_refresh_download_and_refund(browser_stage, tmp_path, width):
    browser, origin, service, stripe = browser_stage
    context = browser.new_context(ignore_https_errors=True, viewport={'width': width, 'height': 900})
    page = context.new_page()
    run, sid = browser_run(context, origin, service, stripe)
    try:
        page.goto(origin + '/report?run_id=' + run)
        expect(page.locator('#status')).to_have_text('Payment verified. Your report is ready.')
        expect(page.locator('#report')).to_be_visible()
        # The original generated report is reused, with all its decision feedback.
        expected = build_published_report(dict(mode='standard', level='beginner', dayNum=0,
            challenges=[[dict(action='hold', stop=False) for _ in range(12)] for _ in range(6)]))
        assert page.locator('#report').get_attribute('srcdoc') == expected['download_html']
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        assert page.locator('#report').get_attribute('sandbox') == ''
        assert page.url == origin + '/report'
        page.reload()
        expect(page.locator('#status')).to_have_text('Payment verified. Your report is ready.')
        with page.expect_download() as pending:
            page.locator('#download').click()
        download = pending.value
        path = tmp_path / 'verified-report.html'
        download.save_as(path)
        assert path.read_text() == expected['download_html']
        # A refund discovered after display must block the very next download.
        stripe.sessions[sid]['payment_intent']['latest_charge']['refunded'] = True
        page.locator('#download').click()
        expect(page.locator('#report')).to_be_hidden()
        expect(page.locator('#download')).to_be_hidden()
        assert stripe.calls == 1
    finally:
        context.close()


def test_unknown_browser_and_pending_payment_never_unlock_or_charge_again(browser_stage):
    browser, origin, service, stripe = browser_stage
    context = browser.new_context(ignore_https_errors=True)
    run, sid = browser_run(context, origin, service, stripe, paid=False)
    page = context.new_page()
    try:
        page.goto(origin + '/report?run_id=' + run + '&paid=true')
        expect(page.locator('#status')).to_contain_text('Payment confirmation is pending')
        expect(page.locator('#report')).to_be_hidden()
        page.locator('#retry').click()
        expect(page.locator('#status')).to_contain_text('Payment confirmation is pending')
        assert stripe.calls == 1
        stranger = browser.new_context(ignore_https_errors=True)
        try:
            stolen_link = stranger.new_page()
            stolen_link.goto(origin + '/report?run_id=' + run)
            expect(stolen_link.locator('#status')).to_contain_text('Use the original browser')
            expect(stolen_link.locator('#report')).to_be_hidden()
        finally:
            stranger.close()
    finally:
        context.close()
