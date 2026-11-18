// Black-box HTTP regression for the isolated holding service.
// No Stripe calls, database writes, or secrets; must never activate checkout.
import test from 'node:test';
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { createServer } from 'node:net';

async function availablePort() {
  const server = createServer();
  await new Promise((resolve, reject) => {
    server.once('error', reject);
    server.listen(0, '127.0.0.1', resolve);
  });
  const port = server.address().port;
  await new Promise((resolve, reject) => server.close(error => error ? reject(error) : resolve()));
  return port;
}

test('isolated holding HTTP never exposes payment, webhook or report endpoints', {timeout: 30000}, async t => {
  const port = await availablePort();
  const child = spawn(process.execPath, ['web/trading-challenge/server/tiq72-upgrade6-holding-http.mjs'], {
    cwd: process.cwd(),
    env: {
      PATH: process.env.PATH,
      PORT: String(port),
      // Deliberately omit all provider credentials and DB URLs.
      NIJA_GAME_REPORTS_ENABLED: 'false',
      NIJA_GAME_BROWSER_CHECKOUT_ENABLED: 'false',
      TIQ72_LIVE_PAYMENTS_ENABLED: 'false'
    },
    stdio: ['ignore', 'ignore', 'pipe']
  });
  let stderr = '';
  child.stderr.on('data', chunk => { stderr = (stderr + chunk.toString()).slice(-4096); });
  t.after(() => { if (!child.killed) child.kill('SIGTERM'); });
  const base = 'http://127.0.0.1:' + port;
  let healthy;
  for (let attempt = 0; attempt < 100; attempt++) {
    if (child.exitCode !== null) {
      // Only expose an allowlisted error category, never raw stderr or environment values.
      const reason = /ERR_MODULE_NOT_FOUND/.test(stderr) ? 'module_missing' :
        /ERR_[A-Z_]+/.test(stderr) ? (stderr.match(/ERR_[A-Z_]+/) || ['node_error'])[0] :
        /ReferenceError:/.test(stderr) ? 'reference_error' :
        /TypeError:/.test(stderr) ? 'type_error' :
        /SyntaxError:/.test(stderr) ? 'syntax_error' :
        /EADDRINUSE/.test(stderr) ? 'port_in_use' :
        /EACCES|EPERM/.test(stderr) ? 'listen_permission_denied' : 'startup_failed';
      const locations = [...stderr.matchAll(/(?:file:\/\/)?[^\s()]*\/([a-zA-Z0-9_-]+\.mjs):([0-9]+):([0-9]+)/g)];
      const origin = locations.length ? locations[0][1] + ':' + locations[0][2] : 'unknown';
      throw new Error('holding service exited before HTTP readiness: ' + reason + '; source=' + origin + '; code=' + child.exitCode);
    }
    try {
      healthy = await fetch(base + '/healthz', {signal: AbortSignal.timeout(500)});
      break;
    } catch {
      await new Promise(resolve => setTimeout(resolve, 100));
    }
  }
  assert.ok(healthy, 'holding service must start');
  assert.equal(healthy.status, 200);
  const status = await healthy.json();
  assert.equal(status.status, 'holding');
  assert.equal(status.decisions, 72);
  assert.equal(status.checkout_available, false);
  assert.equal(status.report_fulfillment_verified, false);
  assert.equal(status.storage_migrated, false);

  for (const [method, path] of [
    ['POST', '/api/tiq72/checkout'],
    ['POST', '/sandbox/stripe/webhook'],
    ['GET', '/api/tiq72/report'],
    ['GET', '/api/tiq72/score'],
    ['POST', '/api/tiq72/score'],
    ['GET', '/api/tiq72/checkout'],
    ['GET', '/readyz']
  ]) {
    const response = await fetch(base + path, {method});
    assert.equal(response.status, 503, method + ' ' + path);
    assert.equal(response.headers.get('cache-control'), 'no-store');
    assert.equal(response.headers.get('x-content-type-options'), 'nosniff');
    const payload = await response.json();
    assert.equal(payload.checkout_available, false);
  }
});
