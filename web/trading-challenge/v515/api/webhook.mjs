import {respond} from "../server/release-status.mjs";
export default function handler(req,res) { return respond(res,503,{error:"payment_release_not_certified",checkout_available:false}); }
