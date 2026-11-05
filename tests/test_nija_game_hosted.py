"""Five-round report fidelity and guarded hosted checkout tests."""
import os
import unittest
from unittest.mock import patch
from flask import Flask
from nija_game_billing import cookie_name
from nija_game_report_scoring import build_report
from nija_game_hosted_routes import register_hosted_routes

SID="cs_live_0123456789ABCDEFGHIJKLMNOP"
ATTEMPT="l,20,2;s,20,2;w,0,0;w,0,0;l,20,2"
ORIGIN="https://nija-trading-challenge.vercel.app"

class Tests(unittest.TestCase):
 def setUp(self):
  app=Flask(__name__)
  register_hosted_routes(app)
  self.client=app.test_client()

 def test_canonical_report(self):
  r=build_report(ATTEMPT)
  self.assertEqual((r["score"],r["ending_balance_usd"],r["positions"]),(200,10215.52,3))
  self.assertEqual([x["simulated_pnl_usd"] for x in r["rounds"]],[62,82.51,0,0,71.01])
  with self.assertRaises(ValueError):build_report("w,0,0")

 def test_flag_blocks_checkout(self):
  with patch.dict(os.environ,{"NIJA_GAME_BROWSER_CHECKOUT_ENABLED":"false","STRIPE_SECRET_KEY":"sk_live_mock"}):
   self.assertFalse(self.client.get("/game/status").json["checkout_available"])
   self.assertEqual(self.client.post("/game/checkout/start",headers={"Origin":ORIGIN},data={"adult":"yes","attempt":ATTEMPT}).status_code,503)

 def test_origin_age_gate_and_secure_cookie(self):
  with patch.dict(os.environ,{"NIJA_GAME_BROWSER_CHECKOUT_ENABLED":"true","STRIPE_SECRET_KEY":"sk_live_mock"}):
   self.assertEqual(self.client.post("/game/checkout/start",headers={"Origin":"https://attacker.example"},data={"adult":"yes","attempt":ATTEMPT}).status_code,403)
   self.assertEqual(self.client.post("/game/checkout/start",headers={"Origin":ORIGIN},data={"attempt":ATTEMPT}).status_code,403)
   with patch("nija_game_hosted_routes.stripe_client",return_value=object()),patch("nija_game_hosted_routes.create_checkout",return_value=("https://checkout.stripe.com/c/pay/demo","a"*64,SID)):
    r=self.client.post("/game/checkout/start",headers={"Origin":ORIGIN},data={"adult":"yes","attempt":ATTEMPT})
  self.assertEqual(r.status_code,303)
  cookie=r.headers["Set-Cookie"]
  for word in (cookie_name(SID),"HttpOnly","Secure","SameSite=Lax"):self.assertIn(word,cookie)
  self.assertNotEqual(cookie_name(SID),cookie_name(SID+"2"))

 def test_report_requires_proof_even_with_session(self):
  with patch.dict(os.environ,{"STRIPE_SECRET_KEY":"sk_live_mock"}):
   self.assertEqual(self.client.get("/game/results?session_id="+SID).status_code,403)
   self.client.set_cookie(cookie_name(SID),"a"*64)
   with patch("nija_game_hosted_routes.stripe_client",return_value=object()),patch("nija_game_hosted_routes.verify_paid_attempt",return_value=ATTEMPT):
    r=self.client.get("/game/results?session_id="+SID)
  self.assertEqual(r.status_code,200)
  self.assertIn(b"10,215.52",r.data)
  self.assertIn("no-store",r.headers["Cache-Control"])

if __name__=="__main__":unittest.main()
