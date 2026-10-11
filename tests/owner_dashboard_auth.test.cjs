const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const test = require('node:test');

const html = fs.readFileSync(path.join(__dirname, '../owner_dashboard.html'), 'utf8');
const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];

function dashboard(identity) {
  const nodes = new Map();
  const calls = [];
  let reloads = 0;
  const node = id => {
    if (!nodes.has(id)) nodes.set(id, {
      value: '', textContent: '', hidden: true,
      classList: { add() {}, remove() {}, toggle() {} }, addEventListener() {},
    });
    return nodes.get(id);
  };
  node('ownerLoginEmail').value = 'creator@example.test';
  node('ownerLoginPassword').value = 'dummy-test-password';
  const context = vm.createContext({
    URL, Headers, console, setInterval() {}, setTimeout() {}, clearTimeout() {},
    document: { getElementById: node, querySelector() { return null; } },
    window: {
      location: { origin: 'https://dashboard.example.test', reload() { reloads++; } },
      confirm() { return true; },
      async fetch(url, options = {}) {
        calls.push({ url, options });
        const data = url.endsWith('login-config')
          ? { login_url: 'https://login.example.test/api/auth/login' }
          : url.endsWith('/api/auth/login') ? { access_token: 'dummy-test-token' }
          : url.endsWith('/api/admin/me') ? identity : { administrator_granted: true };
        return { ok: true, status: 200, async json() { return data; } };
      },
    },
  });
  vm.runInContext(script, context);
  vm.runInContext('loadStatus = () => {};', context);
  return { context, calls, node, reloads: () => reloads };
}

test('signed-out dashboard never sends private requests', async () => {
  const d = dashboard({});
  await assert.rejects(vm.runInContext('ownerFetch(API_BASE + "/api/owner/status")', d.context), /Sign in/);
  assert.equal(d.calls.length, 0);
});

test('owner sign-in uses existing login and sends bearer only to dashboard origin', async () => {
  const d = dashboard({ is_administrator: true, is_creator: true, can_manage_administrators: true });
  await vm.runInContext('signInOwner({ preventDefault() {} })', d.context);
  assert.equal(d.calls.length, 3);
  assert.equal(d.calls[1].url, 'https://login.example.test/api/auth/login');
  assert.equal(d.calls[1].options.headers.Authorization, undefined);
  assert.equal(d.calls[2].options.headers.get('Authorization'), 'Bearer dummy-test-token');
  assert.equal(d.node('ownerLoginPassword').value, '');
  assert.equal(d.node('administratorAccess').hidden, false);
  assert.match(d.node('sessionIdentity').textContent, /Dante/);
  await assert.rejects(vm.runInContext('ownerFetch("https://elsewhere.example.test/data")', d.context), /Invalid dashboard/);
  assert.equal(d.calls.length, 3);
});

test('delegates have no grant controls and ordinary users cannot enter dashboard', async () => {
  const delegate = dashboard({ is_administrator: true, is_creator: false, can_manage_administrators: false });
  await vm.runInContext('signInOwner({ preventDefault() {} })', delegate.context);
  assert.equal(delegate.node('administratorAccess').hidden, true);
  const ordinary = dashboard({ is_administrator: false });
  await vm.runInContext('signInOwner({ preventDefault() {} })', ordinary.context);
  assert.match(ordinary.node('ownerLoginError').textContent, /not been granted/);
  await assert.rejects(vm.runInContext('ownerFetch(API_BASE + "/api/owner/status")', ordinary.context), /Sign in/);
});

test('revoked authorization clears the session and reloads sensitive data', async () => {
  const d = dashboard({ is_administrator: true, is_creator: true, can_manage_administrators: true });
  await vm.runInContext('signInOwner({ preventDefault() {} })', d.context);
  d.context.window.fetch = async () => ({ status: 403, ok: false });
  await assert.rejects(vm.runInContext('ownerFetch(API_BASE + "/api/owner/status")', d.context), /revoked/);
  assert.equal(d.reloads(), 1);
  await assert.rejects(vm.runInContext('ownerFetch(API_BASE + "/api/owner/status")', d.context), /Sign in/);
});

test('owner grants require an explicit confirmation', async () => {
  const d = dashboard({ is_administrator: true, is_creator: true, can_manage_administrators: true });
  await vm.runInContext('signInOwner({ preventDefault() {} })', d.context);
  d.node('administratorUserId').value = 'subscriber';
  d.context.window.confirm = () => false;
  await vm.runInContext('changeAdministratorAccess(true)', d.context);
  assert.equal(d.calls.length, 3);
  d.context.window.confirm = () => true;
  await vm.runInContext('changeAdministratorAccess(true)', d.context);
  assert.equal(d.calls[3].options.method, 'POST');
  assert.equal(d.calls[3].options.headers.get('Authorization'), 'Bearer dummy-test-token');
});
