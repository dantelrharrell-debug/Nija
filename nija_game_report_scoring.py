"""Port of canonical five-round buildReport, independent of brokerage trading."""
from __future__ import annotations
import math
from nija_game_billing import decode_attempt, OFFER

SCENARIOS = (
 ("The rising trend","long",(.3,.8,1.7,1.3,2.5,3.1),"Define your risk before pursuing a trend. A positive setup is not a promise of profit."),
 ("The weak support level","short",(-.3,-1.2,-.7,-2,-3.4,-4.1),"In real markets short selling has risks that this simplified game does not model."),
 ("The sideways trap","wait",(.2,-.3,.15,-.4,.1,-.1),"Passing on an unclear trade can be an intelligent risk-management choice."),
 ("The headline spike","wait",(1.1,-1.8,1.4,-2.7,1.6,-3.2),"Volatility can punish impulsive decisions. Sometimes the best strategy is to wait."),
 ("The structured retest","long",(-.4,.6,1.3,2,2.7,3.5),"A trading plan should specify your thesis, invalidation point and acceptable loss."),
)
def round2(x):
 return math.floor((x+2.220446049250313e-16)*100+.5)/100

def build_report(attempt):
 entries=decode_attempt(attempt)
 balance,score,stopouts,positions=10000.,0,0,0
 rows=[]
 for i,(entry,sc) in enumerate(zip(entries,SCENARIOS)):
  title,optimal,moves,lesson=sc
  choice=entry["choice"]
  size,stop=(0.,0.) if choice=="wait" else (float(entry["size"]),float(entry["stop"]))
  stopped,pct=False,0.
  if choice!="wait":
   positions+=1
   sign=1 if choice=="long" else -1
   for move in moves:
    if move*sign<=-stop:
     pct,stopped=-stop,True
     break
   if not stopped: pct=moves[-1]*sign
  risk=balance*size*stop/10000.
  pnl=balance*size*pct/10000.
  balance=max(0.,balance+pnl)
  points=40 if choice==optimal else (20 if choice=="wait" else 12)
  score+=points
  stopouts+=int(stopped)
  rows.append(dict(round=i+1,scenario=title,decision=choice,optimal=optimal,position_size_percent=size,stop_percent=stop,planned_risk_usd=round2(risk),simulated_pnl_usd=round2(pnl),stop_triggered=stopped,points=points,feedback=lesson))
 choices=[r["decision"] for r in rows]
 strengths,focus=[],[]
 if choices[2]==choices[3]=="wait": strengths.append("You resisted low-conviction and high-volatility setups.")
 else: focus.append("Practice patience when there is no clear setup or price moves are unusually volatile.")
 if all(r["decision"]=="wait" or r["position_size_percent"]*r["stop_percent"]/100<=1 for r in rows): strengths.append("Each simulated trade stayed within the 1% account-risk rule.")
 if choices[0]==choices[4]=="long": strengths.append("You identified two fictional bullish trading structures.")
 if stopouts: focus.append("Review your stop placement and distinguish normal volatility from a thesis failure.")
 if any(r["points"]<40 for r in rows): focus.append("Revisit your lower-scoring scenarios, and explain the evidence behind each choice.")
 if not focus: focus.append("Keep a written trading journal and rehearse how your plan handles unexpected news.")
 tier="Risk-first strategist" if score>=170 else ("Developing discipline" if score>=130 else "Learning the fundamentals")
 return dict(title="Your NIJA Personal Results",report_version=OFFER,virtual_money_only=True,score=score,out_of=200,tier=tier,starting_balance_usd=10000,ending_balance_usd=round2(balance),simulated_pnl_usd=round2(balance-10000),positions=positions,stop_outs=stopouts,strengths=strengths,areas_to_practice=focus,rounds=rows,disclaimer="For educational simulation only. Fictional prices, no brokerage account, no investment advice or guaranteed future performance.")
