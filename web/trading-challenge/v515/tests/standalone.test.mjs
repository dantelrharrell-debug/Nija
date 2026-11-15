import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createHash} from 'node:crypto';
import {previewSimulationAllowed} from '../src/lib/tiqReportReopen.js';
import {releaseStatus} from '../server/release-status.mjs';
import {ROUNDS,CHALLENGES,SCENARIOS,replayRun} from '../offline_tiq_premium/tiq_engine.mjs';
const root=new URL('../',import.meta.url);
test('all source files match the pinned report-copy revision',()=>{
 const hashes=JSON.parse(readFileSync(new URL('approved-source-hashes.json',root)));
 for(const [file,hash] of Object.entries(hashes)) assert.equal(createHash('sha256').update(readFileSync(new URL(file,root))).digest('hex'),hash,file);
});
test('six scenarios have twelve decisions each',()=>{assert.equal(ROUNDS,12);assert.equal(CHALLENGES,6);assert.equal(SCENARIOS.length,6);assert.equal(ROUNDS*CHALLENGES,72);});
test('all hosted previews and production deny local simulated report unlock',()=>{
 for(const host of ['game.nijaaitrading.com','nijaaitrading.com','example.vercel.app','attacker.example','localhost.attacker.example','']) assert.equal(previewSimulationAllowed(host),false,host);
 assert.equal(previewSimulationAllowed('localhost'),true);
});
test('environment flag cannot activate unverified payment',()=>{
 process.env.NIJA_REPORT_CHECKOUT_ENABLED='true'; assert.equal(releaseStatus.checkout_available,false); assert.equal(releaseStatus.live_payments,false);assert.equal(releaseStatus.trading_enabled,false);
});
for(const route of ['checkout','results','recovery','webhook']) test(route+' fails closed without calling Stripe or granting reports',async()=>{
 const {default:handler}=await import('../api/'+route+'.mjs');
 const res={setHeader(){},end(body){this.body=JSON.parse(body);}};
 handler({method:'POST',body:{paid:true,amount:100}},res);
 assert.equal(res.statusCode,503);assert.equal(res.body.checkout_available,false);
});
test('no IONOS telemetry or platform SDK needed to start free game',()=>{
 const telemetry=readFileSync(new URL('src/lib/visitorTracking.js',root),'utf8'); assert.doesNotMatch(telemetry,/import |fetch\(|sendBeacon|pocketbase/i);
 const pkg=JSON.parse(readFileSync(new URL('package.json',root))); assert.equal(pkg.dependencies['@heycatch/sdk'],undefined);
});
