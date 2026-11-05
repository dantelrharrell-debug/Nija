import test from 'node:test';
import assert from 'node:assert/strict';
import {buildReport, evaluateRun, validateRun, renderReportHtml} from './ionos_published_report.mjs';
import {reducer, initialState} from '../tests/fixtures/ionos_served_ui_reference.mjs';

// Compare the actual UI reducer with the report's independent replay logic.
for (const mode of ['standard', 'daily']) {
  for (const level of ['beginner', 'intermediate', 'advanced']) {
    for (const strategy of ['hold', 'buy', 'sell', 'mixed']) {
      test(`${mode}/${level}/${strategy}: report equals UI for all 72 decisions`, () => {
        const day = mode === 'daily' ? 20762 : 0;
        let state = reducer({...initialState, mode, level}, {type:'start', dayNum:day});
        const feedback = [];
        for (let i = 0; i < 72; i++) {
          const action = strategy === 'mixed' ? ['buy','hold','sell','buy','buy','hold','sell'][i % 7] : strategy;
          state = reducer(state, {type:'stop', on:i % 3 === 0});
          state = reducer(state, {type:'trade', action});
          feedback.push(state.feedback);
          state = reducer(state, {type:'next'});
        }
        assert.equal(state.screen, 'done');
        assert.equal(state.decLog.length, 72);
        const payload = {mode, level, dayNum:day, challenges:Array.from({length:6}, (_, i) => state.decLog.slice(i*12,(i+1)*12))};
        const scored = evaluateRun(payload), report = buildReport(payload);
        assert.equal(report.tradingIQ, state.runs.at(-1).avg);
        assert.equal(scored.results.length, 6);
        for (let i = 0; i < 6; i++) {
          const actual = state.results[i], replay = scored.results[i];
          assert.equal(replay.score, actual.score);
          assert.equal(replay.ret, actual.ret);
          assert.equal(replay.maxDD, actual.maxDD);
          assert.equal(replay.trades, actual.trades);
          assert.equal(replay.stopUsed, actual.stopUsed);
          assert.equal(replay.final, Math.round(actual.final*100)/100);
        }
        const history = report.challenges.flatMap(c => c.decisions);
        assert.equal(history.length, 72);
        for (let i=0;i<72;i++) {
          assert.equal(history[i].action, state.decLog[i].action);
          assert.equal(history[i].stopArmed, state.decLog[i].stop);
          assert.equal(history[i].head, feedback[i].head);
          assert.equal(history[i].text, feedback[i].text);
        }
        for (const a of Object.values(report.assessments)) assert.ok(a.score >= 0 && a.score <= 100);
        assert.ok(report.lessons.every(l => ['ages-18-25','ages-26-45','ages-46-65'].includes(l.ageGroup)));
        assert.ok(report.lessons.length <= 4);
        const html = renderReportHtml(report);
        assert.ok(!html.includes('<script'));
        assert.ok(html.includes('width=device-width'));
        assert.ok(html.includes('overflow-x:auto'));
        assert.equal((html.match(/scope="row"/g) || []).length, 75);
      });
    }
  }
}
test('incomplete run, forged score and invalid action/stop are rejected', () => {
  const valid = {mode:'standard',level:'beginner',dayNum:0,
    challenges:Array.from({length:6},()=>Array.from({length:12},()=>({action:'hold',stop:false})))};
  for (const payload of [{...valid,challenges:valid.challenges.slice(0,1)}, {...valid,score:100},
    {...valid,challenges:Array.from({length:6},()=>Array.from({length:12},()=>({action:'long',stop:'true'})))}]) {
    assert.equal(validateRun(payload).ok,false);
    assert.equal(buildReport(payload),null);
  }
});
