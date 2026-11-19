import test from "node:test";
import assert from "node:assert/strict";
import {startVerifiedTestCheckout} from "../server/v515-test-checkout.mjs";
import {PaidReportDenied,TEST_PRICE,TEST_PRODUCT,ISOLATED_TEST_PRICE,ISOLATED_TEST_PRODUCT} from "../server/verified-report-service.mjs";
const ownerId="owner-test",attemptKey=["12345678","90abcdef"].join(""),origin="https://game.nijaaitrading.com";
const canonicalRun={mode:"standard",level:"beginner",dayNum:0,
 challenges:Array.from({length:6},()=>Array.from({length:12},()=>({action:"hold",stop:false})))};
function fixture(testOffer) {
 const expectedPrice=testOffer?.price??TEST_PRICE;
 const expectedProduct=testOffer?.product??TEST_PRODUCT;
 let priceCalls=0,created=0,attached=0,reserved=0,previous=null;
 const price={id:expectedPrice,livemode:false,active:true,product:expectedProduct,
   unit_amount:100,currency:"usd",type:"one_time"};
 const session={id:"cs_test_fixture",livemode:false,mode:"payment",status:"open",
   payment_status:"unpaid",client_reference_id:"reservation-test",
   metadata:{tiq72_reservation_id:"reservation-test"},
   url:"https://checkout.stripe.com/c/pay/cs_test_fixture"};
 const store={
   reserveAuthenticatedRun:async(q)=>{
     reserved++;assert.ok(/^[a-f0-9]{64}$/.test(q.canonicalDigest));
     return previous||{runId:"run-test",reservationId:"reservation-test",
       sessionId:null,state:"reserved"};
   },
   attachVerifiedTestCheckout:async(q)=>{
     attached++;assert.equal(q.sessionId,session.id);
   }
 };
 const stripe={
   prices:{retrieve:async()=>{priceCalls++;return price}},
   checkout:{sessions:{
     create:async(params,opts)=>{
       created++;
       assert.equal(params.client_reference_id,"reservation-test");
       assert.equal(params.line_items[0].price,expectedPrice);
       assert.equal(params.metadata.tiq72_version,"v515-72-decisions");
       assert.ok(opts.idempotencyKey.includes("reservation-test"));
       return session;
     },
     retrieve:async()=>session
   }}
 };
 const run=(opts={})=>startVerifiedTestCheckout({ownerId,attemptKey,
   adultAttested:true,canonicalRun,trustedOrigin:origin,store,stripe,testOffer,...opts});
 return {run,price,session,get created(){return created},
   get priceCalls(){return priceCalls},get attached(){return attached},
   get reserved(){return reserved},set previous(x){previous=x;}};
}
test("creates one validated Stripe TEST Checkout and persists binding",async()=>{
 const f=fixture(),result=await f.run();
 assert.equal(result.checkoutUrl,f.session.url);assert.equal(f.created,1);
 assert.equal(f.attached,1);assert.equal(f.reserved,1);
});
test("retries existing bound checkout without creating another session",async()=>{
 const f=fixture();f.previous={runId:"run-test",reservationId:"reservation-test",
   sessionId:"cs_test_fixture",state:"checkout_created"};
 const result=await f.run();assert.equal(result.checkoutUrl,f.session.url);
 assert.equal(f.created,0);assert.equal(f.attached,1);
});
test("rejects wrong adult eligibility before provider call",async()=>{
 const f=fixture();await assert.rejects(f.run({adultAttested:"true"}),/authenticated_adult_checkout_required/);
 assert.equal(f.priceCalls,0);
});
test("rejects incomplete 72-decision input",async()=>{
 const f=fixture();await assert.rejects(f.run({canonicalRun:{...canonicalRun,challenges:[]}}),/canonical_72_decisions_required/);
 assert.equal(f.priceCalls,0);
});
test("rejects injected browser scoring",async()=>{
 const f=fixture();await assert.rejects(f.run({canonicalRun:{...canonicalRun,score:100}}),/canonical_72_decisions_required/);
});
test("rejects live or wrong test price",async()=>{
 const f=fixture();f.price.livemode=true;await assert.rejects(f.run(),/verified_test_price_required/);
 assert.equal(f.reserved,0);
});
test("rejects host manipulation of trusted origin",async()=>{
 const f=fixture();await assert.rejects(f.run({trustedOrigin:"https://evil.example"}),/trusted_return_origin_required/);
 assert.equal(f.reserved,0);
});
test("rejects refund, dispute, or already-paid attempt",async()=>{
 const f=fixture();f.previous={runId:"run-test",reservationId:"reservation-test",
   sessionId:"cs_test_fixture",state:"refunded"};
 await assert.rejects(f.run(),/paid_or_revoked_attempt_not_repeatable/);
 assert.equal(f.created,0);
});
test("rejects live Checkout session before attaching",async()=>{
 const f=fixture();f.session.livemode=true;
 await assert.rejects(f.run(),/test_checkout_session_required/);assert.equal(f.attached,0);
});
test("rejects non-Stripe hosted payment URL",async()=>{
 const f=fixture();f.session.url="https://example.net/pay";
 await assert.rejects(f.run(),/hosted_checkout_url_required/);assert.equal(f.attached,0);
});

test("approved isolated TEST offer is used for pricing and Checkout, legacy default retained",async()=>{
 const f=fixture({price:ISOLATED_TEST_PRICE,product:ISOLATED_TEST_PRODUCT});
 const result=await f.run();
 assert.equal(f.priceCalls,1);
 assert.equal(f.created,1);
 assert.equal(result.runId,"run-test");
 const legacy=fixture();
 await legacy.run();
 assert.equal(legacy.created,1);
});
test("unapproved TEST offer is rejected before any provider requests",async()=>{
 const f=fixture({price:"price_untrusted",product:ISOLATED_TEST_PRODUCT});
 await assert.rejects(f.run(),/test_product_mismatch/);
 assert.equal(f.priceCalls,0);
 assert.equal(f.created,0);
});
