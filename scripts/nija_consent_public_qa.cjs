'use strict';

// Anonymous, GET-only visual review of NIJA's public consent pages.
// No credentials, cookies, form submissions, provider calls, or personal data.
const { chromium } = require('playwright');
const fs = require('node:fs/promises');
const path = require('node:path');

const origin = 'https://nijaaitrading.com';
const allowedHosts = new Set(['nijaaitrading.com', 'www.nijaaitrading.com']);
const outputDir = path.resolve('artifacts/nija-consent-visual');
const routes = [
  ['free', '/free'],
  ['apply', '/apply'],
  ['opt-out', '/ai-voice-opt-out'],
  ['admin-login', '/admin/ai-voice-consent'],
];
const viewports = [
  { name: 'mobile', viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true },
  { name: 'desktop', viewport: { width: 1440, height: 900 }, isMobile: false, hasTouch: false },
];

async function inspect(browser, viewport, slug, route) {
  const entry = { route, viewport: viewport.name, status: null, phoneInputs: 0,
    aiVoiceCheckboxes: 0, checkedAiVoiceCheckboxes: 0, issues: [], screenshot: null };
  const context = await browser.newContext({
    viewport: viewport.viewport, isMobile: viewport.isMobile,
    hasTouch: viewport.hasTouch, locale: 'en-US', deviceScaleFactor: 1,
  });
  try {
    const page = await context.newPage();
    const response = await page.goto(origin + route, { waitUntil: 'domcontentloaded', timeout: 30000 });
    entry.status = response ? response.status() : null;
    await page.waitForTimeout(1800); // allow client-side route hydration, but never click
    const lastUrl = new URL(page.url());
    entry.finalPath = lastUrl.pathname; // discard query strings and all tokens
    if (!allowedHosts.has(lastUrl.hostname)) {
      entry.issues.push('unexpected_cross_origin_redirect');
      return entry; // do not capture third-party login pages
    }
    if (!entry.status || entry.status >= 400) entry.issues.push('http_error');
    const body = await page.locator('body').innerText().catch(() => '');
    if (body.trim().length < 80) entry.issues.push('short_or_empty_rendered_body');
    entry.phoneInputs = await page.locator('input[type="tel"], input[name*="phone" i], input[id*="phone" i]').count();
    const aiBoxes = page.getByRole('checkbox', { name: /ai|artificial|generated|automated|voice/i });
    entry.aiVoiceCheckboxes = await aiBoxes.count();
    for (let index = 0; index < entry.aiVoiceCheckboxes; index += 1) {
      if (await aiBoxes.nth(index).isChecked()) entry.checkedAiVoiceCheckboxes += 1;
    }
    if (entry.checkedAiVoiceCheckboxes) entry.issues.push('ai_voice_checkbox_prechecked');
    if ((slug === 'apply' || slug === 'free') && entry.phoneInputs && !entry.aiVoiceCheckboxes) {
      entry.issues.push('phone_field_without_recognizable_ai_voice_checkbox');
    }
    if (slug === 'opt-out' && !/withdraw|opt.out|revoke|unsubscribe/i.test(body)) {
      entry.issues.push('opt_out_text_not_detected');
    }
    const exposedAdminActions = slug === 'admin-login'
      ? await page.getByRole('button', { name: /^(approve|reject|show full number)$/i }).count()
      : 0;
    if (exposedAdminActions) {
      entry.issues.push('anonymous_admin_actions_visible');
      return entry; // no screenshot if a private claim could be exposed
    }
    if (slug === 'admin-login' && !/sign.in|log.in|authenticate/i.test(body)) {
      entry.issues.push('admin_gate_needs_manual_security_review');
      return entry; // avoid exporting potentially private data
    }
    const filename = viewport.name + '-' + slug + '.png';
    await page.screenshot({ path: path.join(outputDir, filename), fullPage: true, animations: 'disabled' });
    entry.screenshot = filename;
  } catch (error) {
    entry.issues.push('browser_or_route_error:' + String(error?.name || 'error').slice(0, 60));
  } finally {
    await context.close();
  }
  return entry;
}

async function main() {
  await fs.mkdir(outputDir, { recursive: true });
  const results = [];
  const browser = await chromium.launch({ headless: true });
  try {
    for (const viewport of viewports) {
      for (const [slug, route] of routes) {
        const result = await inspect(browser, viewport, slug, route);
        results.push(result);
        console.log(JSON.stringify({ route, viewport: viewport.name, status: result.status,
          issues: result.issues, screenshot: result.screenshot }));
      }
    }
  } finally {
    await browser.close();
  }
  const report = {
    note: 'Public anonymous visual reconnaissance only; does NOT certify consent, admin authorization, server persistence, or JustCall readiness.',
    testedAtUtc: new Date().toISOString(), origin, results,
  };
  await fs.writeFile(path.join(outputDir, 'results.json'), JSON.stringify(report, null, 2) + '\n');
  if (results.some((result) => result.issues.length > 0)) process.exitCode = 1;
}

main().catch((error) => {
  console.error('Anonymous browser QA could not start:', error?.name || 'unknown_error');
  process.exitCode = 1;
});
