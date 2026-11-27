import React,{useEffect,useState} from "react";
import {Link,useLocation} from "react-router";
import TiqReport from "../components/TiqReport.jsx";
import {loadTiqTestReturn,testReturnPreviewEnabled} from "../lib/tiqTestPaymentReturn.mjs";

const messages={
  loading:"Checking your test payment…",
  invalid:"This is not a valid test payment return link.",
  sign_in:"An eligible signed-in account is needed to open this report. Sign in through the approved test account flow, then return here.",
  unavailable:"This report is unavailable to this account or the test payment was reversed.",
  pending:"Stripe has not confirmed the test payment yet. Try again in a moment.",
  retry:"The test report could not be loaded. Try again."
};

export default function TiqTestPaymentReturn(){
  const {search}=useLocation();
  const [result,setResult]=useState({state:"loading"});
  const [attempt,setAttempt]=useState(0);
  const enabled=testReturnPreviewEnabled(import.meta.env.VITE_TIQ72_TEST_RETURN_ENABLED,window.location.hostname);
  useEffect(()=>{
    if(!enabled)return;
    const controller=new AbortController();
    let current=true;
    setResult({state:"loading"});
    loadTiqTestReturn(search,{signal:controller.signal}).then(data=>{if(current)setResult(data);});
    return ()=>{current=false;controller.abort();};
  },[enabled,search,attempt]);
  return <main className="tiq-card">
    <h1>Trading IQ report</h1>
    {!enabled?<p>Online report retrieval is not available here yet.</p>:<>
      <p>This is a TEST preview. No real payment was taken.</p>
      {result.state==="ready"
        ?<TiqReport report={result.report} preview={false} onClose={()=>setResult({state:"closed"})}/>
        :<p role="status">{messages[result.state]}</p>}
      {["retry","pending","sign_in"].includes(result.state)&&
        <button type="button" onClick={()=>setAttempt(n=>n+1)}>Check again</button>}
    </>}
    <Link to="/trading-iq-challenge">Back to the free challenge</Link>
  </main>;
}
