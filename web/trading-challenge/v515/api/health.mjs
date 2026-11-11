import {releaseStatus,respond} from "../server/release-status.mjs";
export default function handler(req,res) { return respond(res,req.method === "GET" ? 200 : 405,releaseStatus); }
