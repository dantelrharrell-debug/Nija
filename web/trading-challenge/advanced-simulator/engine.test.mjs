import test from 'node:test';
import assert from 'node:assert/strict';
import {createRun,trade,advance,snapshot,history} from './engine.mjs';
const candles=[{open:100,high:110,low:90,close:100},{open:100,high:120,low:95,close:110}];
test('deterministic virtual round trip',()=>{
  const a=createRun({candles}),b=createRun({candles});
  for(const r of [a,b]){trade(r,'buy',2);advance(r);trade(r,'sell',2);}
  assert.deepEqual(snapshot(a),snapshot(b));assert.equal(snapshot(a).position,0);
  assert.ok(snapshot(a).equity>10000);
});
test('reject overspend, naked sell, and exposure breach',()=>{
  const r=createRun({candles,maxExposure:0.1});
  assert.throws(()=>trade(r,'buy',100000));
  assert.throws(()=>trade(r,'sell',1));
  assert.throws(()=>trade(r,'buy',11),/exposure/);
  assert.equal(snapshot(r).events,0);
});
test('invalid candles and orders are rejected',()=>{
  assert.throws(()=>createRun({candles:[{open:2,high:1,low:1,close:1},candles[1]]}));
  const r=createRun({candles});
  for(const q of [NaN,-1,Infinity,0])assert.throws(()=>trade(r,'buy',q));
});
test('future candles cannot be read through run or snapshot',()=>{
  const source=candles.map(c=>({...c}));const r=createRun({candles:source});
  assert.deepEqual(Object.keys(r),['kind']);
  assert.equal(snapshot(r).price,100);
  source[0].close=9999;source[1].close=9999;
  assert.equal(snapshot(r).price,100);
  assert.equal(advance(r).price,110);
  assert.throws(()=>advance(r),/ended/);
});
test('event log is immutable copy',()=>{
  const r=createRun({candles});trade(r,'buy',1);
  assert.equal(history(r).length,1);
  assert.throws(()=>history(r).push({}));
});
test('invalid run handles rejected',()=>assert.throws(()=>snapshot({}),/unknown run/));
