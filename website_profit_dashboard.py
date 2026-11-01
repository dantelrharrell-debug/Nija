"""Read-only NIJA private-profit review page. No private evidence or credentials in HTML."""
from __future__ import annotations
import secrets
from flask import Blueprint, Response

HTML = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex,nofollow,noarchive"><title>NIJA | Profit per visitor</title>
<style nonce="__NONCE__">
:root{font-family:system-ui,sans-serif;color-scheme:dark;color:#ecf5ff;background:#091628}
*{box-sizing:border-box}main{max-width:1000px;margin:auto;padding:26px 18px}
h1{font-size:clamp(26px,4vw,38px);line-height:1.2}.brand{color:#60c8fc;font-weight:800;letter-spacing:.1em}
p{line-height:1.5;color:#bbcee4}.panel,.metric{background:#14283e;border:1px solid #4a6684;border-radius:12px;padding:19px}
form{display:grid;grid-template-columns:1fr 1.3fr auto;gap:14px;align-items:end}
label{display:block;font-size:14px;font-weight:700;margin-bottom:6px}input{width:100%;background:#06182a;border:1px solid #839db9;color:#fff;border-radius:7px;padding:12px;min-height:46px}
button{min-height:46px;border:0;border-radius:7px;background:#257fe9;color:#fff;font-weight:750;padding:10px 18px}
button:disabled{opacity:.6}input:focus-visible,button:focus-visible{outline:3px solid #69befe}
.cards{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-top:16px}
.metric{min-width:0}.metric span{display:block;color:#baccdf;font-size:13px}.metric strong{display:block;font-size:clamp(17px,2vw,25px);overflow-wrap:anywhere}
#state{font-weight:800;color:#ffe0a7}small{color:#bbcee4}footer{margin-top:25px;border-top:1px solid #4a6684;padding-top:16px}
@media(max-width:730px){form{grid-template-columns:1fr}.cards{grid-template-columns:repeat(2,1fr)}}
@media(max-width:440px){.cards{grid-template-columns:1fr}}
</style></head><body><main>
<p class="brand">NIJA AI TRADING · PRIVATE FINANCIAL REVIEW</p>
<h1>Net operating profit per website visitor</h1>
<p>Business target: <b>$1.00 in average net profit per verified unique visitor.</b>
Visitors are not charged $1 for viewing the site; the target is not a guarantee.</p>
<section class="panel"><h2>Review a completed calendar month</h2>
<p>Verified figures appear only with independently signed, reconciled revenue, cost and visitor evidence.</p>
<form id="f" autocomplete="off">
<div><label for="period">Month (UTC)</label><input id="period" type="month" required autocomplete="off"></div>
<div><label for="secret">Private reporting token</label><input id="secret" type="password" required autocomplete="off" spellcheck="false"></div>
<button type="submit" id="load">Load report</button></form>
<p><small>Use only NIJA's verified billing hostname. The token is submitted in a same-origin authorization header, not saved in the browser, URL, or analytics.</small></p>
<p id="state" role="status" aria-live="polite">UNVERIFIED — No certified evidence loaded. Missing amounts are not zero.</p></section>
<section class="cards" aria-label="Certified figures">
<div class="metric"><span>Unique visitors</span><strong id="visitors">Unverified</strong></div>
<div class="metric"><span>Qualified leads</span><strong id="leads">Unverified</strong></div>
<div class="metric"><span>Collected gross revenue</span><strong id="gross">Unverified</strong></div>
<div class="metric"><span>Refunds</span><strong id="refunds">Unverified</strong></div>
<div class="metric"><span>Attributable costs (includes fees)</span><strong id="costs">Unverified</strong></div>
<div class="metric"><span>Payment processing fees (cost subset)</span><strong id="fees">Unverified</strong></div>
<div class="metric"><span>Net operating profit</span><strong id="profit">Unverified</strong></div>
<div class="metric"><span>Net profit per visitor</span><strong id="pervisitor">Unverified</strong></div>
<div class="metric"><span>Meets the $1 target</span><strong id="target">Unverified</strong></div>
</section><section class="panel"><h2>Evidence coverage</h2><p id="coverage">Visitor identity and consent, collected payments, all refunds, and attributable costs require independent reconciliation.</p>
<p><small>Calendar-month accounting only. Seven-, 30- and 90-day rolling metrics require separate certified daily evidence.</small></p></section>
<footer><small>Read-only report. This page never initiates customer billing, lead outreach, or trading.</small></footer>
</main><script nonce="__NONCE__">
"use strict";
(()=>{
const specs={visitors:["unique_visitors","count"],leads:["unique_qualified_leads","count"],
gross:["gross_collected_revenue_usd","usd"],refunds:["refunds_usd","usd"],
costs:["verified_costs_usd","usd"],fees:["processor_fees_usd","usd"],
profit:["net_profit_usd","usd"],pervisitor:["net_profit_per_visitor_usd","usd"],target:["visitor_target_met","bool"]};
const month=document.getElementById("period"),password=document.getElementById("secret"),btn=document.getElementById("load"),state=document.getElementById("state");
const now=new Date();month.value=new Date(Date.UTC(now.getUTCFullYear(),now.getUTCMonth()-1,1)).toISOString().slice(0,7);
const usd=new Intl.NumberFormat("en-US",{style:"currency",currency:"USD"});
const count=new Intl.NumberFormat("en-US",{maximumFractionDigits:0});
function clear(){Object.keys(specs).forEach(k=>document.getElementById(k).textContent="Unverified")}
function put(msg){state.textContent=msg}
function view(v,kind){if(v==null)return "Unverified";
if(kind==="bool")return v===true?"YES":v===false?"NO":"Unverified";
if(kind==="count")return typeof v==="number"&&Number.isSafeInteger(v)&&v>=0?count.format(v):"Unverified";
return typeof v==="string"&&/^-?[0-9]+(?:\.[0-9]{1,2})?$/.test(v)?usd.format(Number(v)):"Unverified";}
document.getElementById("f").addEventListener("submit",async e=>{
e.preventDefault();clear();document.getElementById("coverage").textContent="Reconciliation not verified.";
const period=month.value,token=password.value;password.value="";
if(!/^[0-9]{4}-(?:0[1-9]|1[0-2])$/.test(period)||!token){put("UNVERIFIED — Enter a valid month and administrator token.");return;}
btn.disabled=true;put("CHECKING — Looking for certified evidence.");
try{const r=await fetch("/api/admin/website-profit?period="+encodeURIComponent(period),{
method:"GET",headers:{Authorization:"Bearer "+token,Accept:"application/json"},
cache:"no-store",credentials:"omit",mode:"same-origin",redirect:"error"});
if(!r.ok){put(r.status===503?"UNVERIFIED — Private reporting configuration or evidence is unavailable.":r.status===401?"UNVERIFIED — Invalid administrator token.":"UNVERIFIED — Reporting API unavailable.");return;}
const data=await r.json(),status=data.source_status||{};
const verified=data.status==="verified"&&data.verification_status==="VERIFIED"&&
status.visitor_counts_verified===true&&status.provider_revenue_verified===true&&
status.all_costs_verified===true&&status.reporting_period_closed===true&&
status.revenue_evidence_complete===true&&status.cost_evidence_complete===true;
if(!verified){put("UNVERIFIED — Missing or incomplete independently certified evidence.");return;}
for(const [id,entry] of Object.entries(specs)){
if(id==="leads"&&status.qualified_leads_verified!==true)continue;
document.getElementById(id).textContent=view(data[entry[0]],entry[1]);}
put("VERIFIED — Signed revenue, costs, and visitors reconciled for a closed month.");
document.getElementById("coverage").textContent="Visitor counts, provider revenue, costs and reporting month certified. Qualified leads: "+(status.qualified_leads_verified===true?"certified.":"not yet certified.");
}catch(_){put("UNVERIFIED — Cannot reach secure reporting API.");}finally{btn.disabled=false;}
});
})();
</script></body></html>"""


def create_dashboard_blueprint() -> Blueprint:
    """Static shell is public; all financial data stays behind existing bearer API."""
    bp = Blueprint("website_profit_dashboard", __name__)

    @bp.get("/admin/revenue-per-visitor")
    def dashboard() -> Response:
        nonce = secrets.token_urlsafe(24)
        page = HTML.replace("__NONCE__", nonce)
        result = Response(page, mimetype="text/html")
        result.headers["Cache-Control"] = "no-store, private"
        result.headers["Pragma"] = "no-cache"
        result.headers["X-Content-Type-Options"] = "nosniff"
        result.headers["X-Frame-Options"] = "DENY"
        result.headers["Referrer-Policy"] = "no-referrer"
        result.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(), payment=()"
        result.headers["Content-Security-Policy"] = (
            "default-src 'none'; "
            f"script-src 'nonce-{nonce}'; style-src 'nonce-{nonce}'; "
            "connect-src 'self'; form-action 'none'; base-uri 'none'; "
            "object-src 'none'; frame-ancestors 'none'"
        )
        return result

    return bp
