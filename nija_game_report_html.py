"""Static HTML presentation for independently verified NIJA educational reports."""
from html import escape

CSS = """body{margin:0;background:#071a24;color:#edfff6;font:16px/1.65 system-ui,sans-serif}
main{max-width:840px;margin:auto;padding:32px 20px 80px}
a{color:#8cf5ca}h1{font-size:clamp(30px,6vw,52px);line-height:1.2}
h2{margin-top:34px}.brand{color:#8cf5ca;font-weight:900;letter-spacing:2px}
.score{font-size:24px;font-weight:800}.cols{display:grid;grid-template-columns:1fr 1fr;gap:16px}
.card{background:#10303c;border:1px solid #305e62;border-radius:12px;padding:20px;margin:14px 0}
.note{font-size:13px;color:#bbd3d3}@media(max-width:650px){.cols{grid-template-columns:1fr}}"""

def money(value):
    return ("-" if value < 0 else "") + "${:,.2f}".format(abs(value))

def render(report=None, error=None):
    e = escape
    body = ""
    if error is not None:
        body = "<h1>Report not available</h1><p>" + e(error) + "</p><p>Open this page in the same browser that completed payment. If you were charged, contact NIJA support with your Stripe receipt.</p>"
    else:
        r = report
        body = ("<p>NIJA Personalized Results · one-time $1 report</p>"
                "<h1>" + e(r["tier"]) + "</h1>"
                "<p class='score'>Discipline score: " + str(r["score"]) + " / 200</p>"
                "<p>Ending virtual balance: <strong>" + money(r["ending_balance_usd"]) +
                "</strong> · Simulated P&amp;L: <strong>" + money(r["simulated_pnl_usd"]) + "</strong></p>"
                "<h2>Your learning priorities</h2><div class='cols'>")
        for heading, key in (("Strengths", "strengths"), ("Areas to practice", "areas_to_practice")):
            body += "<section class='card'><h3>" + heading + "</h3><ul>"
            for item in r[key]:
                body += "<li>" + e(item) + "</li>"
            body += "</ul></section>"
        body += "</div><h2>Your five market decisions</h2>"
        for row in r["rounds"]:
            body += ("<section class='card'><h3>Round " + str(row["round"]) + ": " +
                     e(row["scenario"]) + "</h3><p>Your choice: <strong>" +
                     e(row["decision"]) + "</strong> · Educational reference: " +
                     e(row["optimal"]) + "</p><p>Position: " +
                     str(row["position_size_percent"]) + "% · Stop: " +
                     str(row["stop_percent"]) + "% · Points: " +
                     str(row["points"]) + "/40</p><p>Planned risk: " +
                     money(row["planned_risk_usd"]) + " · Virtual P&amp;L: " +
                     money(row["simulated_pnl_usd"]) + "</p><p>" + e(row["feedback"]) + "</p></section>")
        body += "<p class='note'>" + e(r["disclaimer"]) + "</p>"
    return ("<!doctype html><html lang='en'><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width, initial-scale=1'>"
            "<meta name='robots' content='noindex,nofollow'>"
            "<title>NIJA Personalized Results</title><style>" + CSS +
            "</style></head><body><main><p class='brand'>NIJA AI TRADING</p>" + body +
            "<p><a href='https://nija-trading-challenge.vercel.app/'>Return to the free game</a></p>"
            "</main></body></html>")
