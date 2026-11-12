import test from 'node:test';
import assert from 'node:assert/strict';
import { scoreTiq72ServerSide, validateTiq72Submission, TIQ72_DECISIONS } from '../server/tiq72-authoritative-adapter.mjs';
import { replayRun } from '../v515/offline_tiq_premium/tiq_engine.mjs';

const choices=['buy','sell','hold'];
function fixture(seed,mode='standard') {
  let n=seed>>>0;
  const next=()=>{n=(Math.imul(n,1664525)+1013904223)>>>0;return n;};
  return {mode,level:['beginner','intermediate','advanced'][next()%3],
    dayNum:mode==='daily'?next()%20000:0,
    challenges:Array.from({length:6},()=>Array.from({length:12},()=>({
      action:choices[next()%3],stop:(next()&1)===1,
    })))};
}
test('approved engine contract has 72 decisions, no browser-supplied scores',()=>{
 const input=fixture(41);assert.equal(TIQ72_DECISIONS,72);
 const result=scoreTiq72ServerSide(input);
 assert.equal(result.validatedDecisions,72);
 assert.equal(result.results.length,6);
 assert.equal(result.score,replayRun(input).summary.avg);
 assert.match(result.runDigest,/^[a-f0-9]{64}$/);
});
test('200 seeded authoritative comparisons for standard and daily runs',()=>{
 for(let seed=1;seed<=200;seed++){
  const input=fixture(seed,seed%2?'standard':'daily');
  const expected=replayRun(input),actual=scoreTiq72ServerSide(input);
  assert.equal(actual.score,expected.summary.avg,`seed ${seed}`);
  assert.deepEqual(actual.summary,expected.summary,`seed ${seed}`);
  assert.deepEqual(actual.results,expected.results,`seed ${seed}`);
  assert.equal(actual.run.challenges.flat().length,72);
 }
});
test('rejects missing, altered, oversized, and extra-field runs',()=>{
 const input=fixture(99);
 for(const bad of [
  {...input,challenges:input.challenges.slice(1)},
  {...input,challenges:[...input.challenges, input.challenges[0]]},
  {...input,challenges:input.challenges.map((c,i)=>i===0?c.slice(1):c)},
  {...input,score:100},
  {...input,challenges:input.challenges.map((c,i)=>i===0?c.map((d,j)=>j===0?{...d,score:100}:d):c)},
  {...input,challenges:input.challenges.map((c,i)=>i===0?c.map((d,j)=>j===0?{action:'hack',stop:true}:d):c)},
  {...input,dayNum:4},
 ])assert.throws(()=>validateTiq72Submission(bad));
});
