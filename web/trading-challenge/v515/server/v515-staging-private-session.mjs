// Review-only reader for an existing TEST host session store. Never mints a
// cookie, accepts an Authorization header, or exposes stored bearer tokens.
import {createHash} from "node:crypto";

export const TIQ72_TEST_SESSION_COOKIE="__Host-nija-tiq72-test";
const SUBJECT=/^tiq-stage-[a-z0-9-]{1,64}$/;
const OPAQUE=/^[A-Za-z0-9_-]{43}$/;
const DIGEST=/^[a-f0-9]{64}$/;
const CSRF=/^[A-Za-z0-9_-]{32,96}$/;
const MAX_AGE_MS=15*60*1000;
const MAX_COOKIE_BYTES=4096;

function credential(req){
  const header=req?.headers?.cookie;
  if(typeof header!=="string"||Buffer.byteLength(header)>MAX_COOKIE_BYTES) return null;
  let raw=null;
  for(const entry of header.split(";")){
    const part=entry.trim();
    const index=part.indexOf("=");
    if(index<0){
      if(part===TIQ72_TEST_SESSION_COOKIE) return null;
      continue;
    }
    const name=part.slice(0,index);
    if(name.trim()!==TIQ72_TEST_SESSION_COOKIE) continue;
    if(name!==TIQ72_TEST_SESSION_COOKIE||raw!==null) return null;
    raw=part.slice(index+1);
  }
  if(raw===null||!OPAQUE.test(raw)||Buffer.from(raw,"base64url").toString("base64url")!==raw) return null;
  return raw;
}

export function createTiq72PrivateSessionReader({
  enabled=false,lookupByDigest,now=Date.now
}={}){
  if(enabled!==true) return async ()=>null;
  if(typeof lookupByDigest!=="function"||typeof now!=="function")
    throw new TypeError("private_test_session_lookup_required");
  return async req=>{
    const opaque=credential(req);
    if(opaque===null) return null;
    const digest=createHash("sha256").update(opaque,"ascii").digest("hex");
    // Contract: trusted private lookup with transport and storage security.
    // A lookup outage propagates to the existing route's fail-closed 503.
    const row=await lookupByDigest(digest);
    const time=now();
    if(!row||row.active!==true||row.revokedAt!==null||
       typeof row.tokenDigest!=="string"||!DIGEST.test(row.tokenDigest)||row.tokenDigest!==digest||
       typeof row.subject!=="string"||!SUBJECT.test(row.subject)||
       typeof row.csrfToken!=="string"||!CSRF.test(row.csrfToken)||
       typeof row.accessToken!=="string"||row.accessToken.length>4089||
       !Number.isSafeInteger(time)||!Number.isSafeInteger(row.issuedAt)||!Number.isSafeInteger(row.expiresAt)||
       row.issuedAt<0||row.issuedAt>time||row.expiresAt<=time||row.expiresAt-row.issuedAt>MAX_AGE_MS) return null;
    return {active:true,subject:row.subject,csrfToken:row.csrfToken,accessToken:row.accessToken};
  };
}
