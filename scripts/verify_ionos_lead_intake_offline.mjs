import fs from 'node:fs';
import vm from 'node:vm';
import { webcrypto } from 'node:crypto';
import assert from 'node:assert/strict';

// Offline source-review harness only. No real database, browser, provider or customer account.
// Run: node --experimental-vm-modules scripts/verify_ionos_lead_intake_offline.mjs [exported-source]
// The default fixture is an exact IONOS preview export, not an installed application module.
const source = fs.readFileSync(process.argv[2] || new URL('../tests/fixtures/ionos/leadIntake.preview-20261111.js', import.meta.url), 'utf8');
const cases = [];
const test = (name, run) => cases.push({name, run});
async function fixture() {
  const events = new Map(), receipts = [], storage = new Map(), requests = [];
  const state = {fail: false, lostResponse: false, external: 0};
  const pb = {
    collection(name) {
      return {async create(row) {
        if (name !== 'nija_lead_events') { receipts.push(row); return row; }
        if (state.fail) throw {status: 503};
        if (events.has(row.event_id)) throw {status:400,response:{data:{event_id:{code:'validation_not_unique'}}}};
        events.set(row.event_id, structuredClone(row));
        if (state.lostResponse) { state.lostResponse=false; throw {status:0}; }
        return row;
      }};
    },
    async send(path, options) { requests.push({path,body:options.body}); return {recorded:true,decision:'granted'}; }
  };
  const outside = () => { state.external++; throw Error('External I/O forbidden'); };
  const context=vm.createContext({crypto:webcrypto,TextEncoder,console:{error(){}},fetch:outside,
    XMLHttpRequest:outside,WebSocket:outside,Image:outside,navigator:{sendBeacon:outside},
    sessionStorage:{getItem:k=>storage.get(k),setItem:(k,v)=>storage.set(k,v),removeItem:k=>storage.delete(k)},
    window:{addEventListener(){}},location:{pathname:'/offline'},setTimeout,clearTimeout});
  const mod=new vm.SourceTextModule(source,{context});
  await mod.link(async specifier => {
    if(specifier==='./pb.js') return new vm.SyntheticModule(['pb'],function(){this.setExport('pb',pb)},{context});
    if(specifier==='./visitorTracking.js') return new vm.SyntheticModule(['trackVisitorEvent'],function(){this.setExport('trackVisitorEvent',()=>{})},{context});
    throw Error('Unexpected import: '+specifier);
  });
  await mod.evaluate();
  return {api:mod.namespace,events,receipts,storage,requests,state};
}
const input = (id,extra={}) => ({form_name:'free_trader_assessment',email:'offline@synthetic.local',name:'Offline Fixture',fields:{answer:1},submission_id:id,...extra});
test('storage failure never reports success or sends',async()=>{
  const f=await fixture();f.state.fail=true;await assert.rejects(f.api.submitLead(input('intent-a')));
  assert.equal(f.events.size,0);assert.equal(f.requests.length,0);assert.equal(f.state.external,0);
});
test('same intent concurrent retry is stored once',async()=>{
  const f=await fixture();const [a,b]=await Promise.all([f.api.submitLead(input('intent-a')),f.api.submitLead(input('intent-a'))]);
  assert.equal(a.event_id,b.event_id);assert.equal(f.events.size,1);assert.equal(f.state.external,0);
});
test('lost response retry retains event and consent timestamp',async()=>{
  const f=await fixture();f.state.lostResponse=true;await assert.rejects(f.api.submitLead(input('intent-a')));
  const before=[...f.events.values()][0];await f.api.submitLead(input('intent-a'));
  assert.equal(f.events.size,1);const after=[...f.events.values()][0];assert.equal(before.event_id,after.event_id);
  assert.equal(before.submitted_at,after.submitted_at);assert.equal(before.consent_detail.consent_timestamp,after.consent_detail.consent_timestamp);
});
test('separate explicit intents with identical answers stay distinct',async()=>{
  const f=await fixture();const a=await f.api.submitLead(input('intent-a'));const b=await f.api.submitLead(input('intent-b'));
  assert.notEqual(a.event_id,b.event_id);assert.equal(f.events.size,2);
});
test('separate explicit consent decision is preserved',async()=>{
  const f=await fixture();await f.api.submitLead(input('intent-a',{consent:{marketing_email:false}}));
  await f.api.submitLead(input('intent-b',{consent:{marketing_email:true}}));
  assert.equal(f.events.size,2);assert.equal([...f.events.values()][1].consent_marketing_email,true);
});
test('same intent changed content is rejected without another row',async()=>{
  const f=await fixture();await f.api.submitLead(input('intent-a'));
  await assert.rejects(f.api.submitLead(input('intent-a',{fields:{answer:2}})));
  assert.equal(f.events.size,1);
});
test('same intent changed consent is rejected without another row',async()=>{
  const f=await fixture();await f.api.submitLead(input('intent-a',{consent:{marketing_email:false}}));
  await assert.rejects(f.api.submitLead(input('intent-a',{consent:{marketing_email:true}})));
  assert.equal(f.events.size,1);
});
test('capture has no provider I/O and never reports email sent',async()=>{
  const f=await fixture();const r=await f.api.submitLead(input('intent-a'));
  assert.equal(f.state.external,0);assert.notEqual(r.delivery.email,'sent');assert.notEqual(r.delivery.zapier,'sent');
  assert.ok(f.receipts.every(x=>x.status!=='sent'));
});
let failures=0;
for (const {name,run} of cases) {try {await run();console.log('PASS',name);}catch(e){failures++;console.log('FAIL',name, e.message);}}
console.log(JSON.stringify({passed:cases.length-failures,failed:failures}));
process.exitCode=failures?1:0;
