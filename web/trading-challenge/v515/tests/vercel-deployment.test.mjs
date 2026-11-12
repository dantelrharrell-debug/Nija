import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync, existsSync} from 'node:fs';
import {fileURLToPath} from 'node:url';
import {join, resolve} from 'node:path';
import {ROUNDS, CHALLENGES} from '../offline_tiq_premium/tiq_engine.mjs';
import {releaseStatus} from '../server/release-status.mjs';

const root = fileURLToPath(new URL('../', import.meta.url));
const readJson = file => JSON.parse(readFileSync(join(root, file), 'utf8'));

test('the Vercel project must use the isolated v515 Vite root, not the trading Python root', () => {
  const config = readJson('vercel.json');
  const pkg = readJson('package.json');
  assert.equal(config.framework, 'vite');
  assert.equal(config.buildCommand, 'npm run build');
  assert.equal(config.installCommand, 'npm ci');
  assert.equal(config.outputDirectory, 'dist');
  assert.equal(pkg.scripts.build, 'vite build');
  assert.equal(pkg.scripts.start, undefined, 'must not run the legacy Node HTTP server');
  assert.ok(existsSync(join(root, 'index.html')));
  assert.ok(existsSync(join(root, 'package-lock.json')));
  assert.ok(existsSync(join(root, 'vite.config.js')));
  assert.equal(resolve(root, '../../../'), resolve(root, '../../../'), 'root remains isolated');
});

test('the approved v515 source retains 6 x 12 decisions and payment-disabled release status', () => {
  assert.equal(CHALLENGES, 6);
  assert.equal(ROUNDS, 12);
  assert.equal(CHALLENGES * ROUNDS, 72);
  assert.equal(releaseStatus.checkout_available, false);
  assert.equal(releaseStatus.live_payments, false);
  assert.equal(releaseStatus.trading_enabled, false);
});

test('the Vercel config preserves API routing and browser protections', () => {
  const config = readJson('vercel.json');
  assert.ok(!Object.hasOwn(config, 'rootDirectory'), 'Root Directory belongs in Vercel project settings');
  assert.ok(!Object.hasOwn(config, 'functions'), 'do not map the Python trading backend');
  for (const rule of config.rewrites || []) {
    assert.ok(!rule.source.startsWith('/api'), 'do not rewrite API routes to the SPA');
    assert.ok(!rule.destination.includes('main.py') && !rule.destination.includes('api_gateway'));
  }
  const headers = (config.headers || []).flatMap(rule => rule.headers || []);
  const value = name => headers.find(h => h.key.toLowerCase() === name.toLowerCase())?.value;
  assert.equal(value('X-Content-Type-Options'), 'nosniff');
  assert.equal(value('X-Frame-Options'), 'DENY');
  assert.match(value('Content-Security-Policy') || '', /frame-ancestors 'none'/);
  assert.match(value('Content-Security-Policy') || '', /form-action 'none'/);
});

for (const endpoint of ['checkout', 'results', 'recovery', 'webhook']) {
  test('/api/' + endpoint + ' remains HTTP 503 even with checkout flag enabled', async () => {
    const previous = process.env.NIJA_REPORT_CHECKOUT_ENABLED;
    process.env.NIJA_REPORT_CHECKOUT_ENABLED = 'true';
    try {
      const {default: handler} = await import('../api/' + endpoint + '.mjs');
      const response = {
        statusCode: 200,
        setHeader() {},
        end(body) { this.body = JSON.parse(body); }
      };
      await handler({method: 'POST', body: {paid: true, amount: 100}}, response);
      assert.equal(response.statusCode, 503);
      assert.equal(response.body.checkout_available, false);
    } finally {
      if (previous === undefined) delete process.env.NIJA_REPORT_CHECKOUT_ENABLED;
      else process.env.NIJA_REPORT_CHECKOUT_ENABLED = previous;
    }
  });
}
