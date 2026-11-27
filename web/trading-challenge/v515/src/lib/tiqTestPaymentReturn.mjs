// Same-origin protected staging only. A Stripe session ID is a lookup pointer,
// never authorization. No browser storage, embedded token, or cross-site call.
const STAGING_HOST="nija-trading-challenge-staging.vercel.app";
const TEST_SESSION=/^cs_test_[A-Za-z0-9]{8,220}$/;

export function testReturnPreviewEnabled(flag,hostname){
  return flag==="true"&&hostname===STAGING_HOST;
}
export async function loadTiqTestReturn(search,{request=fetch,signal}={}){
  const params=new URLSearchParams(search);
  const ids=params.getAll("session_id");
  if(params.size!==1||ids.length!==1||!TEST_SESSION.test(ids[0]))
    return {state:"invalid"};
  try{
    const r=await request("/sandbox/report/return?session_id="+encodeURIComponent(ids[0]),{
      credentials:"same-origin",cache:"no-store",redirect:"error",signal,
      headers:{Accept:"application/json"}
    });
    const status={401:"sign_in",403:"unavailable",404:"unavailable",409:"pending",429:"retry"};
    if(!r.ok) return {state:status[r.status]??"retry"};
    if(!r.headers.get("content-type")?.includes("application/json")) return {state:"retry"};
    const data=await r.json();
    const report=data?.report;
    if(!Number.isFinite(report?.tradingIQ)||report.rounds!==12||
       !Array.isArray(report.challenges)||report.challenges.length!==6||
       !report.assessments) return {state:"retry"};
    return {state:"ready",report};
  }catch{
    return {state:"retry"};
  }
}
