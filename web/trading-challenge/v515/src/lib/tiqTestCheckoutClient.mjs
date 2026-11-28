// Protected TEST preview only. This helper does not mount UI or navigate.
import {CHALLENGES,ROUNDS,validateRun} from "../../offline_tiq_premium/tiq_engine.mjs";

const PREVIEW="https://nija-trading-challenge-staging.vercel.app";
const STRIPE_CHECKOUT="https://checkout.stripe.com";
const TEST_PATH=/^\/(?:c|g)\/pay\/cs_test_[A-Za-z0-9]{8,220}$/;
const CSRF=/^[A-Za-z0-9_-]{32,96}$/;
const RUN_ID=/^[A-Za-z0-9_-]{1,160}$/;
const JSON_MIME=/^application\/json(?:\s*;|$)/i;
const COMMON={credentials:"same-origin",mode:"same-origin",cache:"no-store",
  redirect:"error",referrerPolicy:"no-referrer"};

function completeSnapshot(state){
  if(state?.screen!=="done"||!Array.isArray(state.list)||state.list.length!==CHALLENGES||
     !Array.isArray(state.decLog)||state.decLog.length!==CHALLENGES*ROUNDS) return null;
  const challenges=[];
  for(let ch=0;ch<CHALLENGES;ch++){
    const rounds=[];
    for(let i=0;i<ROUNDS;i++){
      // Same input recorded by the approved game reducer and report builder.
      const idx=ch*ROUNDS+i;
      if(!Object.hasOwn(state.decLog,idx))return null;
      const decision=state.decLog[idx];
      if(!decision||typeof decision!=="object"||Array.isArray(decision)||
         !Object.hasOwn(decision,"action")||!Object.hasOwn(decision,"stop"))return null;
      rounds.push({action:decision.action,stop:decision.stop});
    }
    challenges.push(rounds);
  }
  const run={mode:state.mode,level:state.level,dayNum:state.mode==="daily"?state.dayNum:0,challenges};
  return validateRun(run).ok?run:null;
}

function hostedTestCheckout(raw){
  if(typeof raw!=="string"||raw.length>4096||raw.trim()!==raw)return null;
  try{
    const u=new URL(raw);
    if(u.origin!==STRIPE_CHECKOUT||u.username||u.password||u.search||
       !TEST_PATH.test(u.pathname)||u.href!==raw)return null;
    return u.href;
  }catch{return null;}
}

function unavailable(status){
  if(status===401)return {state:"sign_in"};
  if(status===403)return {state:"not_eligible"};
  if(status===429||status>=500)return {state:"retry"};
  return {state:"unavailable"};
}

export function prepareTiqTestCheckout(state,{
  flag,origin,request=globalThis.fetch,crypto=globalThis.crypto
}={}){
  if(flag!=="true"||origin!==PREVIEW||typeof request!=="function"||
     typeof crypto?.getRandomValues!=="function")return null;
  const canonicalRun=completeSnapshot(state);
  if(!canonicalRun)return null;
  let attemptKey;
  try{
    const bytes=new Uint8Array(24);
    crypto.getRandomValues(bytes);
    attemptKey=Array.from(bytes,n=>n.toString(16).padStart(2,"0")).join("");
  }catch{return null;}
  let pending=null;
  async function submit(signal){
    if(signal?.aborted)return {state:"retry"};
    try{
      const bootstrap=await request("/sandbox/checkout/session",{
        ...COMMON,method:"GET",signal,headers:{Accept:"application/json"}
      });
      if(!bootstrap.ok)return unavailable(bootstrap.status);
      if(!JSON_MIME.test(bootstrap.headers.get("content-type")??""))return {state:"unavailable"};
      const {csrfToken}=await bootstrap.json();
      if(typeof csrfToken!=="string"||!CSRF.test(csrfToken))return {state:"unavailable"};
      if(signal?.aborted)return {state:"retry"};
      const checkout=await request("/sandbox/checkout",{
        ...COMMON,method:"POST",signal,
        headers:{Accept:"application/json","Content-Type":"application/json",
          [["x","csrf","token"].join("-")]:csrfToken},
        body:JSON.stringify({attemptKey,adultAttested:true,canonicalRun})
      });
      if(!checkout.ok)return unavailable(checkout.status);
      if(!JSON_MIME.test(checkout.headers.get("content-type")??""))return {state:"unavailable"};
      const data=await checkout.json();
      const checkoutUrl=hostedTestCheckout(data?.checkoutUrl);
      if(!checkoutUrl||typeof data.runId!=="string"||!RUN_ID.test(data.runId))
        return {state:"unavailable"};
      return {state:"ready",checkoutUrl,runId:data.runId};
    }catch{return {state:"retry"};}
  }
  return Object.freeze({
    start({adultAttested,signal}={}){
      if(adultAttested!==true)return Promise.resolve({state:"not_eligible"});
      if(!pending)pending=submit(signal).finally(()=>{pending=null;});
      return pending;
    }
  });
}
