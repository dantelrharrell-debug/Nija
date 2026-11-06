import test from 'node:test';
import assert from 'node:assert/strict';
import {PreviewReportController, returnRunId} from '../game_sandbox/preview-controller.mjs';
import {installPreview} from '../game_sandbox/install-preview.mjs';
import {reducer, initialState} from './fixtures/ionos_served_ui_reference.mjs';

function completedGame() {
  let state = reducer(initialState, {type: 'start', dayNum: 20762});
  for (let i = 0; i < 72; i++) {
    state = reducer(state, {type: 'stop', on: i % 3 === 0});
    state = reducer(state, {type: 'trade', action: ['buy', 'hold', 'sell'][i % 3]});
    state = reducer(state, {type: 'next'});
  }
  assert.equal(state.screen, 'done');
  return state;
}
function fixture() {
  const calls = [];
  const client = {
    runId: null,
    async resumeSaved() { calls.push('resumeSaved'); return false; },
    async start(value) { calls.push(['start', value]); this.runId = 'a'.repeat(48); },
    async completePublishedGame(value) { calls.push(['complete', value]); },
    async checkout() { calls.push('checkout'); return {url: 'https://checkout.stripe.com/c/pay/test'}; },
    async resume(id) { calls.push(['resume', id]); this.runId = id; },
    async request(path) { calls.push(path); return {report: {report: {tradingIQ: 50}}}; },
  };
  return {client, calls, controller: new PreviewReportController(client)};
}

test('original reducer completion flows to existing client without scores; double click is single flight', async () => {
  const {controller, calls} = fixture();
  const game = completedGame();
  const one = controller.purchase(game, true);
  assert.equal(controller.purchase(game, true), one);
  assert.equal(await one, 'https://checkout.stripe.com/c/pay/test');
  assert.deepEqual(calls.filter(x => x === 'checkout'), ['checkout']);
  const payload = calls.find(x => x[0] === 'complete')[1];
  assert.deepEqual(payload.decisions, game.decLog);
  assert.equal('results' in payload, false);
  assert.equal('runs' in payload, false);
});
test('youth, incomplete and restored runs never start payment requests', async () => {
  for (const [game, adult] of [[completedGame(), false], [initialState, true], [{...completedGame(), restored: true}, true]]) {
    const {controller, calls} = fixture();
    await assert.rejects(controller.purchase(game, adult));
    assert.deepEqual(calls, []);
  }
});
test('lost receipt and immutable older run never fall back to a new charge', async () => {
  for (const failure of ['ownership_required', 'run_is_immutable']) {
    const {client, controller, calls} = fixture();
    client.resumeSaved = async () => {
      calls.push('resumeSaved');
      if (failure === 'ownership_required') throw Error(failure);
      client.runId = 'a'.repeat(48); return true;
    };
    client.completePublishedGame = async () => { throw Error(failure); };
    await assert.rejects(controller.purchase(completedGame(), true), new RegExp(failure));
    assert.deepEqual(calls, ['resumeSaved']);
  }
});
test('ambiguous checkout response retries same run and never starts another', async () => {
  const {client, controller, calls} = fixture();
  client.checkout = async () => { throw Error('network_lost'); };
  await assert.rejects(controller.purchase(completedGame(), true), /network_lost/);
  await assert.rejects(controller.purchase(completedGame(), true), /network_lost/);
  assert.equal(calls.filter(x => x[0] === 'start').length, 1);
});
test('return and pending/refunded reports use ownership/report APIs only', async () => {
  const {client, controller, calls} = fixture();
  for (const error of ['verified_webhook_required', 'ownership_required', 'payment_not_valid']) {
    client.request = async path => { calls.push(path); throw Error(error); };
    await assert.rejects(controller.reopen('a'.repeat(48)), new RegExp(error));
  }
  assert.equal(calls.length, 6);
  assert.ok(calls.every(x => Array.isArray(x) ? x[0] === 'resume' : x.endsWith('/report')));
});
test('untrusted checkout destinations and duplicate return parameters are rejected', async () => {
  for (const url of ['https://checkout.stripe.com.evil.test/', 'http://checkout.stripe.com/', 'https://user@checkout.stripe.com/']) {
    const {client, controller} = fixture();
    client.checkout = async () => ({url});
    await assert.rejects(controller.purchase(completedGame(), true), /unexpected_checkout/);
  }
  const run = 'a'.repeat(48);
  assert.equal(returnRunId('?run_id=' + run + '&cancelled=1'), run);
  assert.throws(() => returnRunId('?run_id=' + run + '&run_id=' + run), /invalid_run/);
});

test('unreviewed UI is never patched; refresh without query uses saved owner run', () => {
  assert.throws(() => installPreview('different website build'), /unreviewed_game_build/);
  assert.equal(returnRunId(''), null);
});
