// Protected TEST preview only. The caller must provide canonical NIJA session
// verification, an operator-only same-origin/CSRF boundary, and private storage.
// Never use checkout headers, browser age input or name/email as decision evidence.
const ID=/^[A-Za-z0-9_.-]{1,160}$/;
const CSRF=/^[A-Za-z0-9_-]{32,96}$/;
const ALLOWED=new Set(["approve","revoke"]);
const SIX_MONTHS=180*24*60*60*1000;
const integer=Number.isSafeInteger;

export function createManualAdultReview({
  reviewedTestOnly=false,reviewerId,verifyCustomerSession,verifyReviewerMutation,
  store,now=Date.now,ttlMs=SIX_MONTHS
}={}){
  if(reviewedTestOnly!==true||typeof reviewerId!=="string"||!ID.test(reviewerId)||
     typeof verifyCustomerSession!=="function"||typeof verifyReviewerMutation!=="function"||
     typeof store?.getLatest!=="function"||typeof store?.record!=="function"||
     !integer(ttlMs)||ttlMs<1||ttlMs>SIX_MONTHS||typeof now!=="function"){
    throw new TypeError("isolated_manual_reviewer_required");
  }

  return Object.freeze({
    async verifyBuyer(request){
      const session=await verifyCustomerSession(request);
      if(session?.active!==true || typeof session.ownerId!=="string" ||
         !ID.test(session.ownerId) || typeof session.csrfToken!=="string" ||
         !CSRF.test(session.csrfToken)) return null;
      const record=await store.getLatest(session.ownerId);
      const t=now();
      if(!integer(t)||record?.buyerId!==session.ownerId||record.reviewerId!==reviewerId||
         record.decision!=="approve"||!integer(record.decidedAt)||!integer(record.expiresAt)||
         record.decidedAt<0||record.decidedAt>t||record.expiresAt<=t||
         record.expiresAt-record.decidedAt>ttlMs) return null;
      return {ownerId:session.ownerId,csrfToken:session.csrfToken,active:true,adultVerified:true};
    },

    async recordDecision(request,input){
      // This dependency must authorize an active admin session and confirm CSRF.
      const actor=await verifyReviewerMutation(request);
      if(actor?.active!==true || actor.isOwner!==true || actor.csrfVerified!==true ||
         actor.ownerId!==reviewerId) return {ok:false,reason:"reviewer_required"};
      if(!input||typeof input!=="object"||Array.isArray(input)||
         Object.keys(input).length!==2||!Object.hasOwn(input,"buyerId")||
         !Object.hasOwn(input,"decision")||typeof input.buyerId!=="string"||
         !ID.test(input.buyerId)||input.buyerId===reviewerId||!ALLOWED.has(input.decision))
        return {ok:false,reason:"invalid_review"};
      const decidedAt=now();
      if(!integer(decidedAt)||decidedAt<0||!integer(decidedAt+ttlMs))
        return {ok:false,reason:"review_unavailable"};
      // No document, birth date, verification answer, name or email is accepted.
      // The trusted owner records a per-account outcome after reviewing evidence.
      await store.record({
        buyerId:input.buyerId,reviewerId,decision:input.decision,decidedAt,
        expiresAt:input.decision==="approve"?decidedAt+ttlMs:null
      });
      return {ok:true};
    }
  });
}

// Only compatible with the separate TEST review-table migration. No DDL or
// fallback happens at runtime. Mutations append rather than editing history.
export function createPgManualAdultReviewStore(pool){
  if(typeof pool?.query!=="function") throw new TypeError("private_pg_pool_required");
  return Object.freeze({
    async getLatest(buyerId){
      const result=await pool.query(
        "SELECT buyer_id, reviewer_id, decision, decided_at_ms, expires_at_ms "+
        "FROM tiq72_v515_manual_adult_reviews WHERE buyer_id=$1 ORDER BY review_id DESC LIMIT 1",
        [buyerId]
      );
      const r=result.rows[0];
      return r?{buyerId:r.buyer_id,reviewerId:r.reviewer_id,decision:r.decision,
        decidedAt:Number(r.decided_at_ms),expiresAt:r.expires_at_ms===null?null:Number(r.expires_at_ms)}:null;
    },
    async record(r){
      await pool.query(
        "INSERT INTO tiq72_v515_manual_adult_reviews "+
        "(buyer_id,reviewer_id,decision,decided_at_ms,expires_at_ms) VALUES ($1,$2,$3,$4,$5)",
        [r.buyerId,r.reviewerId,r.decision,r.decidedAt,r.expiresAt]
      );
    }
  });
}
