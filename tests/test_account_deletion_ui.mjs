import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const source = readFileSync(new URL('../frontend/static/js/capacitor-init.js', import.meta.url), 'utf8');

function client({ body = {}, ok = true, signedIn = true, confirmed = true, phrase = 'DELETE MY NIJA ACCOUNT' } = {}) {
    const alerts = [];
    const requests = [];
    const removed = [];
    const sections = [];
    let logouts = 0;
    const document = {
        readyState: 'loading',
        addEventListener() {},
        createElement: () => ({}),
        getElementById: id => id === 'settings-content' ? { appendChild: node => sections.push(node) } : null
    };
    const window = {
        location: { origin: 'https://privacy-test.example.invalid', reload: () => { logouts += 1; } },
        confirm: () => confirmed,
        prompt: () => phrase,
        alert: value => alerts.push(value),
        handleLogout: () => { logouts += 1; }
    };
    const context = vm.createContext({
        window,
        document,
        localStorage: {
            getItem: () => signedIn ? 'synthetic-auth-for-in-memory-test' : null,
            removeItem: key => removed.push(key)
        },
        console: { log() {}, warn() {}, error() {} },
        fetch: async (url, options) => {
            requests.push({ url, options });
            return { ok, json: async () => body };
        },
        URL,
        Set
    });
    vm.runInContext(source, context, { filename: 'capacitor-init.js' });
    return { window, context, alerts, requests, removed, sections, logouts: () => logouts };
}

test('notice explains remaining records and follow-up before a destructive request', () => {
    const ui = client();
    ui.context.ensureAccountDeletionControls();
    assert.equal(ui.requests.length, 0);
    assert.equal(ui.sections.length, 1);
    const notice = ui.sections[0].innerHTML;
    assert.match(notice, /covered by this account-deletion service/);
    assert.match(notice, /does not confirm deletion from every NIJA system/);
    assert.match(notice, /member broker connections/);
    assert.match(notice, /backups/);
    assert.match(notice, /support@nijaaitrading\.com/);
    assert.match(notice, /does not automatically submit that request or cancel/);
});

test('successful cleanup displays the server scope and follow-up before logout', async () => {
    const body = {
        success: true,
        message: 'Only covered active stores were deleted. Provider copies and backups remain outside this request.',
        privacy_follow_up: 'Contact support@nijaaitrading.com for a separate privacy review.'
    };
    const ui = client({ body });
    await ui.window.requestNijaAccountDeletion();
    assert.equal(ui.requests.length, 1);
    assert.equal(ui.requests[0].options.method, 'DELETE');
    assert.equal(ui.requests[0].options.headers.Authorization, 'Bearer synthetic-auth-for-in-memory-test');
    assert.deepEqual(JSON.parse(ui.requests[0].options.body), { confirmation: 'DELETE MY NIJA ACCOUNT' });
    assert.equal(ui.alerts[0], `${body.message}\n\n${body.privacy_follow_up}`);
    assert.deepEqual(ui.removed, ['nija_token', 'nija_risk_acknowledged']);
    assert.equal(ui.logouts(), 1);
});

test('legacy success response uses a limited-scope fallback with a usable contact', async () => {
    const ui = client({ body: { success: true } });
    await ui.window.requestNijaAccountDeletion();
    assert.match(ui.alerts[0], /active stores covered/);
    assert.match(ui.alerts[0], /Other NIJA records/);
    assert.match(ui.alerts[0], /support@nijaaitrading\.com/);
    assert.match(ui.alerts[0], /does not automatically submit that request/);
    assert.equal(ui.logouts(), 1);
});

for (const setup of [
    { name: 'cancelled confirmation', confirmed: false },
    { name: 'incorrect confirmation phrase', phrase: 'wrong' },
    { name: 'missing authentication', signedIn: false }
]) {
    test(`${setup.name} makes no request and preserves local credentials`, async () => {
        const ui = client(setup);
        await ui.window.requestNijaAccountDeletion();
        assert.equal(ui.requests.length, 0);
        assert.equal(ui.removed.length, 0);
        assert.equal(ui.logouts(), 0);
    });
}

test('failed cleanup preserves local state and does not display a success claim', async () => {
    const ui = client({ ok: false, body: { message: 'Cleanup may be partial. Contact support before retrying.' } });
    await ui.window.requestNijaAccountDeletion();
    assert.match(ui.alerts[0], /Account deletion was not confirmed/);
    assert.match(ui.alerts[0], /Cleanup may be partial/);
    assert.equal(ui.removed.length, 0);
    assert.equal(ui.logouts(), 0);
});
