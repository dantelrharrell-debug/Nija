import test from 'node:test';
import assert from 'node:assert/strict';
import {randomBytes} from 'node:crypto';
import {createTiq72OwnerProof} from '../server/tiq72-signed-owner-proof.mjs';
import {createTiq72SignedV515Handler} from '../server/tiq72-v515-auth-adapter.mjs';

const signingKey=randomBytes(32);
const configuration={
  signingKey,
  rateLimit: async()=>true,
  store:{},
  stripe:{},
  webhookSecret:['whsec','testfixture'].join('_'),
  trustedOrigin:'https://game.nijaaitrading.com'
};
function fakeResponse(){
  return {
    headers:{},statusCode:null,body:null,
    setHeader(k,v){this.headers[k.toLowerCase()]=v;},
    end(text){this.body=text;}
  };
}
test('the signed V515 wrapper requires valid dependencies and exact game origin',()=>{
  assert.throws(()=>createTiq72SignedV515Handler({...configuration,signingKey:randomBytes(16)}),
    /signed_isolated/);
  assert.throws(()=>createTiq72SignedV515Handler({...configuration,trustedOrigin:'https://other.invalid'}),
    /signed_isolated/);
  assert.throws(()=>createTiq72SignedV515Handler({...configuration,webhookSecret:''}),
    /signed_isolated/);
});
test('anonymous report recovery cannot read an owner report',async()=>{
  const handler=createTiq72SignedV515Handler(configuration);
  const res=fakeResponse();
  await handler({method:'GET',url:'/sandbox/report?run_id=example',headers:{}},res);
  assert.equal(res.statusCode,401);
  assert.deepEqual(JSON.parse(res.body),{error:'authentication_required'});
});
test('valid signed identity without matching Origin and CSRF cannot start checkout',async()=>{
  const handler=createTiq72SignedV515Handler(configuration);
  const issued=createTiq72OwnerProof({ownerId:'test_owner',adultVerified:true},signingKey);
  const req={method:'POST',url:'/sandbox/checkout',headers:{
    authorization:'Bearer '+issued.token,
    origin:'https://not-the-game.invalid',
    'x-csrf-token':issued.csrfToken
  }};
  const res=fakeResponse();
  await handler(req,res);
  assert.equal(res.statusCode,403);
  assert.deepEqual(JSON.parse(res.body),{error:'request_not_authorized'});
});
