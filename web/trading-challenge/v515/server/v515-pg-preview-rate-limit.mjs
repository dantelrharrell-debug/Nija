// Optional protected TEST preview limiter. Not mounted. No customer data or
// per-client identifiers are written; two service-wide lanes bound storage.
// This does not replace a private ingress/platform abuse limit.
const LIMITS=Object.freeze({authenticated_commerce:30,owner_review:8});
const ISOLATED_DB="nija_tiq72_upgrade6_isolated_test";
const ISOLATED_ROLE="nija_tiq72_upgrade6_isolated_test_user";

export const TAKE_PREVIEW_RATE_LIMIT=`
  INSERT INTO public.tiq72_v515_preview_rate_limits AS prior (lane,window_epoch,hits)
  SELECT $1,floor(extract(epoch FROM statement_timestamp()) / 60)::bigint,1
  WHERE current_database() = $3 AND current_user = $4
  ON CONFLICT (lane) DO UPDATE
  SET window_epoch=EXCLUDED.window_epoch,
      hits=CASE WHEN prior.window_epoch < EXCLUDED.window_epoch THEN 1 ELSE prior.hits+1 END
  WHERE prior.window_epoch < EXCLUDED.window_epoch
     OR (prior.window_epoch = EXCLUDED.window_epoch AND prior.hits < $2)
  RETURNING 1 AS allowed`;

export function createPgPreviewRateLimiter({reviewedTestOnly=false,pool}={}){
  if(reviewedTestOnly!==true)return async()=>false;
  if(typeof pool?.query!=="function")throw new TypeError("exact_private_pg_pool_required");
  return async (_req,lane)=>{
    if(typeof lane!=="string"||!Object.hasOwn(LIMITS,lane))return false;
    try{
      // One reserved slot across instances. No process-local fallback or
      // automatic retry when the DB result is uncertain. Hosts must bound
      // pool acquisition/statement timeouts and never log query payloads.
      const result=await pool.query(TAKE_PREVIEW_RATE_LIMIT,[lane,LIMITS[lane],ISOLATED_DB,ISOLATED_ROLE]);
      return result?.rowCount===1&&Array.isArray(result.rows)&&result.rows.length===1&&result.rows[0]?.allowed===1;
    }catch{return false;}
  };
}
