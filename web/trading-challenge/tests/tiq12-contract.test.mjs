import test from "node:test";
import assert from "node:assert/strict";
import { TIQ12_VERSION, TIQ12_ROUNDS, validateTiq12Manifest,
  validateTiq12Answers, requireAdultCompletedRun, scorePurchasedTiq12,
  ownerProofHash, matchesVerifiedTiq12Payment } from "../server/tiq12-contract.mjs";

const makeManifest = () => ({ version: TIQ12_VERSION, rounds: Array.from({length: 12}, (_, i) => ({
  id: "round_" + (i + 1), category: ["risk", "research", "discipline"][i % 3],
  title: "Fictional round " + (i + 1), choices: [
    {label: "Risky", points: 0, feedback: "Review the downside", lesson: "Risk first"},
    {label: "Measured", points: 5, feedback: "Consider evidence", lesson: "Stay disciplined"},
    {label: "Review", points: 3, feedback: "Pause and reconsider", lesson: "Check assumptions"}
  ]
})) });
const manifest = validateTiq12Manifest(makeManifest());
const answers = manifest.rounds.map(r => ({roundId:r.id,choice:1}));
const proof = "a".repeat(64);
const storedRun = () => ({id:"run_12345",persisted:true,adultConfirmed:true,completedAt:"2026-11-04T12:00:00Z",
 version:TIQ12_VERSION,manifestDigest:manifest.digest, ownerProofHash:ownerProofHash(proof),answers});
const receipt = () => ({
 session:{id:"cs_test_123456789012",mode:"payment",livemode:false,status:"complete",payment_status:"paid",amount_total:100,currency:"usd",
 metadata:{run_id:"run_12345",game_version:TIQ12_VERSION,manifest_digest:manifest.digest,owner_proof_hash:ownerProofHash(proof)},
 payment_intent:{status:"succeeded",amount_received:100,currency:"usd",latest_charge:{status:"succeeded",paid:true,refunded:false,disputed:false,amount_refunded:0}}},
 lineItems:{data:[{quantity:1,amount_total:100,currency:"usd",price:{id:"price_test_123",product:"prod_test_123"}}]},
 proof,storedRun:storedRun(),manifest,expectedPriceId:"price_test_123",expectedProductId:"prod_test_123",livemode:false,
});

test("manifest only accepts twelve unique complete rounds with server-owned scoring", () => {
  assert.equal(manifest.rounds.length,TIQ12_ROUNDS);
  assert.match(manifest.digest,/^[a-f0-9]{64}$/);
  assert.equal(validateTiq12Manifest(makeManifest()).digest,manifest.digest);
  for(const mutate of [x=>x.rounds.pop(),x=>x.rounds[1].id=x.rounds[0].id,
    x=>x.rounds[2].choices[0].points=100,x=>x.rounds[0].choices=[]]){
    const draft=makeManifest();mutate(draft);assert.throws(()=>validateTiq12Manifest(draft),TypeError);
  }
});
test("all twelve answers are required and extraneous client score/payment fields are rejected",()=>{
  assert.equal(validateTiq12Answers(manifest,answers).length,12);
  for(const bad of [answers.slice(0,11),[...answers.slice(0,11),{roundId:"round_12",choice:9}],
    [...answers.slice(0,11),{roundId:"round_12",choice:1,score:100}],
    [...answers.slice(0,11),{roundId:"round_11",choice:1}]])
    assert.throws(()=>validateTiq12Answers(manifest,bad),TypeError);
});
test("adult, durable completion and exact scoring manifest are mandatory",()=>{
  assert.equal(requireAdultCompletedRun(storedRun(),manifest).length,12);
  for(const patch of [{adultConfirmed:false},{persisted:false},{manifestDigest:"f".repeat(64)},
    {completedAt:""},{version:"nija-trading-iq-6-v1"}])
      assert.throws(()=>requireAdultCompletedRun({...storedRun(),...patch},manifest),TypeError);
});
test("private score derives exclusively from server-owned manifest",()=>{
  const result=scorePurchasedTiq12(manifest,storedRun());
  assert.equal(result.score,100);
  assert.equal(result.decisions.length,12);
  assert.equal(result.dimensions.length,3);
  assert.equal(result.dimensions.every(x=>x.score===100),true);
});
test("payment requires exact adult run, receipt proof, 100 cents, charge, product and version",()=>{
  const base=receipt();assert.equal(matchesVerifiedTiq12Payment(base),true);
  const bad=[x=>x.proof="b".repeat(64),x=>x.storedRun.adultConfirmed=false,
    x=>x.session.amount_total=500,x=>x.session.currency="eur",
    x=>x.session.payment_status="unpaid",x=>x.session.metadata.manifest_digest="b".repeat(64),
    x=>x.session.metadata.game_version="six-round",x=>x.session.payment_intent.latest_charge.refunded=true,
    x=>x.session.payment_intent.latest_charge.disputed=true,x=>x.session.payment_intent.latest_charge.amount_refunded=100,
    x=>x.lineItems.data[0].price.id="wrong",x=>x.lineItems.data.push(x.lineItems.data[0]),
    x=>x.expectedPriceId=undefined,x=>x.expectedProductId=undefined,
    x=>x.session.id="cs_live_123456789012",x=>x.livemode="false"];
  for(const change of bad){const item=receipt();change(item);assert.equal(matchesVerifiedTiq12Payment(item),false);}
});
