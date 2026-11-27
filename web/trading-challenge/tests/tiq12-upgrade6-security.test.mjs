import test from 'node:test';
import assert from 'node:assert/strict';
import { createHmac } from 'node:crypto';
import {
 Upgrade6Error, requireTestConfiguration, requireBrowserOrigin, issueOwnerProof,
 hashOwnerProof, requireOwnerProof, fixedTiq12Checkout, verifyTiq12StripeWebhook,
 requireStripeTestSession, requireAdultOptIn,
} from '../server/tiq12-upgrade6-security.mjs';

const CONFIG = {mode:'test',enabled:true,stripeSecret:'sk_test_abcdefgh1234',
 webhookSecret:'whsec_abcdefgh1234',priceId:'price_test_123',
 productId:'prod_test_123',allowedOrigin:'https://nijaaitrading.com'};
const EVENT = {id:'evt_test_12345',type:'checkout.session.completed',livemode:false,data:{object:{id:'cs_test_abcdefgh12345'}}};
const secret=CONFIG.webhookSecret;
const now=1794355200;
const sign=(body,time=now,secretValue=secret)=>`t=${time},v1=${createHmac('sha256',secretValue).update(`${time}.${body}`).digest('hex')}`;

test('test-mode config accepts exact secure origin and only test keys',()=>{
 const result=requireTestConfiguration(CONFIG);assert.equal(result.allowedOrigin,CONFIG.allowedOrigin);
 assert.equal('stripeSecret' in result,false);
 for(const patch of [{stripeSecret:'sk_live_abcdefgh1234'},{enabled:false},{mode:'live'},
  {webhookSecret:'not-a-signing-secret'},{allowedOrigin:'http://nijaaitrading.com'},
  {allowedOrigin:'https://*.nijaaitrading.com'},{allowedOrigin:'https://nijaaitrading.com/path'},
  {allowedOrigin:'https://nijaaitrading.com/'},{priceId:'wrong'}, {productId:'wrong'}]){
  assert.throws(()=>requireTestConfiguration({...CONFIG,...patch}),Upgrade6Error);
 }
});
test('strict browser origin never accepts missing, wildcard or different origins',()=>{
 assert.equal(requireBrowserOrigin(CONFIG.allowedOrigin,CONFIG.allowedOrigin),true);
 for(const bad of [undefined,'*','https://evil.example','https://nijaaitrading.com.evil.example',
 'https://game.nijaaitrading.com','http://nijaaitrading.com'])
   assert.throws(()=>requireBrowserOrigin(bad,CONFIG.allowedOrigin),Upgrade6Error);
});
test('owner proof issuance and constant-time ownership matching',()=>{
 const proof=issueOwnerProof(),second=issueOwnerProof();
 assert.match(proof,/^[a-f0-9]{64}$/);assert.notEqual(proof,second);
 const stored=hashOwnerProof(proof);assert.equal(requireOwnerProof(proof,stored),true);
 assert.throws(()=>requireOwnerProof(second,stored),Upgrade6Error);
 assert.throws(()=>requireOwnerProof('abc',stored),Upgrade6Error);
});
test('checkout intent fixes product and binds privately stored run identities',()=>{
 const intent=fixedTiq12Checkout({runId:'run_'+'a'.repeat(32),
  manifestDigest:'b'.repeat(64),ownerProofHash:'c'.repeat(64),config:CONFIG});
 assert.deepEqual(intent.line_items,[{price:CONFIG.priceId,quantity:1}]);
 assert.equal(intent.metadata.manifest_digest,'b'.repeat(64));
 assert.throws(()=>fixedTiq12Checkout({runId:'run_bad',manifestDigest:'b'.repeat(64),ownerProofHash:'c'.repeat(64),config:CONFIG}));
});
test('signed raw event verifies test mode with fixed timestamp',()=>{
 const body=JSON.stringify(EVENT);
 assert.deepEqual(verifyTiq12StripeWebhook(body,sign(body),secret,{nowSeconds:now}),EVENT);
 assert.deepEqual(verifyTiq12StripeWebhook(Buffer.from(body),sign(body),secret,{nowSeconds:now}),EVENT);
});
test('webhook refuses stale, future, tampered and incorrectly signed data',()=>{
 const body=JSON.stringify(EVENT);
 for (const input of [
  [body,sign(body,now-301)], [body,sign(body,now+301)],
  [body+' ',sign(body)], [body,sign(body,now,'whsec_anothersecret123')],
  [body,'t=bad,v1='+'a'.repeat(64)], [body,'t='+now],
 ])assert.throws(()=>verifyTiq12StripeWebhook(input[0],input[1],secret,{nowSeconds:now}),Upgrade6Error);
});
test('webhook refuses live events and oversized request bodies',()=>{
 const live=JSON.stringify({...EVENT,livemode:true});
 assert.throws(()=>verifyTiq12StripeWebhook(live,sign(live),secret,{nowSeconds:now}));
 const huge='x'.repeat(262145);
 assert.throws(()=>verifyTiq12StripeWebhook(huge,sign(huge),secret,{nowSeconds:now}));
});
test('test Checkout session and adult opt-in fail closed',()=>{
 assert.equal(requireStripeTestSession('cs_test_abcdefgh12345'),'cs_test_abcdefgh12345');
 for(const s of ['cs_live_abcdefgh12345','cs_test_abc','not_a_session'])
  assert.throws(()=>requireStripeTestSession(s));
 assert.equal(requireAdultOptIn({confirmedAdult:true,paidReportOptIn:true}),true);
 for(const value of [{confirmedAdult:false,paidReportOptIn:true},
  {confirmedAdult:true,paidReportOptIn:false},{}]) assert.throws(()=>requireAdultOptIn(value));
});
