// Entrypoint exclusively for the new, independent education staging service.
import { createEducationStagingServer } from "./tiq12-education-staging.mjs";
const port = Number(process.env.PORT ?? "10000");
if (!Number.isSafeInteger(port) || port < 1 || port > 65535) {
  throw new Error("Invalid PORT");
}
createEducationStagingServer().listen(port, "0.0.0.0", () => {
  console.log("NIJA Trading IQ 12 education staging: HOLDING; checkout disabled");
});
