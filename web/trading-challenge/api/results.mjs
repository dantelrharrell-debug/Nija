import { handle } from "../server/index.mjs";

// Vercel Node function: the same protected handler used by the local server.
export default function resultsHandler(request, response) {
  return handle(request, response);
}
