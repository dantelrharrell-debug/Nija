# NIJA IONOS production lead preservation: owner-operated API export (REVIEW ONLY)

Status: SOURCE PREPARATION ONLY. NOT RUN ON IONOS LIVE, NOT A RESTORED BACKUP, NOT PERMISSION TO DISPATCH. GitHub issue #3421 is open.

## Why this alternative exists

IONOS Support confirmed November 13 that AI App & Site Builder's Code > Export all exports website files, **not the separate PocketBase database**. A public website health response is not an authenticated data-read capability. The published `/free`, `/founding-waitlist`, and `/apply` forms store into `/.sfs-be/` PocketBase, not Render's independently restorable lead databases.

This source provides a proposed self-service, owner-controlled, **read-only** encrypted record export when (and only when) NIJA has a legitimate PocketBase API bearer token with LIST and collection-schema permissions. **Official PocketBase documentation states collection schema reads require a superuser-level token.** A normal authenticated NIJA site-admin or visitor session may not have this capability and must not be treated as equivalent; use only an already authorized, approved credential, never elevate permissions simply for this tool. It uses only GET requests against `https://nijaaitrading.com/.sfs-be`. It does not ask for passwords, change rules, configure Zapier, call Resend or Apollo, invoke the trading bot, or post form submissions.

## How to run on a separately controlled computer, not production

1. Obtain an existing authorized **read-only** PocketBase token through the approved account-authentication mechanism and keep it only in the private local environment variable `NIJA_IONOS_PB_READ_TOKEN`. Never paste tokens in ChatGPT, GitHub, logs, browser console screenshots, or command history. Do not use a public visitor token or elevate access. If a proper authorized token does not exist, this route is BLOCKED; do not bypass permissions.
2. Use a **recipient public RSA key/certificate only** on the collection machine. Its private counterpart must remain separate and access restricted. Reusing the existing protected recovery certificate is possible only after independently verifying compatibility and custody; it has **not** been performed here.
3. From an isolated checkout of the reviewed commit, with Node 22 or newer:

   `node scripts/ionos_lead_readonly_export.mjs --certificate /PRIVATE/recipient_public_cert.pem --output /RESTRICTED/ionos-leads-20261113.enc.json`

   Optional `--extra-collections collection_a,collection_b` may include the *verified actual names* of older applicant/consent collections, but the extra collection names must come from an authenticated inventory, not guesses. The exporter does not export `nija_settings` because it may contain private webhook credentials.
4. It requires collection schema plus full paginated records for all four required collections: `nija_lead_events`, `nija_lead_delivery`, `nija_lead_dispatch`, and `nija_consent_events`. Failure to access **any** collection or schema, a redirect, omitted page, duplicate ID, schema change or two-pass drift FAILS CLOSED and writes **no backup**. Missing/forbidden data is never recorded as zero.
5. Successful output is a new file with exclusive-create permissions 0600 containing only AES-256-GCM ciphertext and an RSA-OAEP wrapped symmetric key. No plaintext customer records are written to disk by the tool. Do not place this encrypted export or keys in GitHub or any publicly accessible folder.
6. Verify independently on a second controlled host, with the privately held recipient key:

   `node scripts/ionos_lead_readonly_verify.mjs --input /RESTRICTED/ionos-leads-20261113.enc.json --private-key /PRIVATE/recipient_private_key.pem`

   The verifier checks the GCM tag and the full logical schema/row digests. It outputs only aggregate collection counts, not customer information. Do not run it in a publicly shared CI runner with private keys.

## Critical limitation: not a database-level backup

Two stable read passes can detect many concurrent inserts/updates/deletes, but do not create a transaction spanning multiple collections. Unobserved concurrent changes, hidden collections, file attachments, auth users, secrets, server runtime and indexes beyond returned collection definitions can still be missing. Thus success is **ENCRYPTED LOGICAL EXPORT ONLY, NOT TRANSACTIONAL DATABASE RESTORE CERTIFICATION**. After successful capture, verify all required actual collections, preserve original IDs, timestamps, consent decisions and delivery history, and separately restore into disposable isolated PocketBase with matching version and schema before treating it as recoverable.

A 403, 404, expired token, or missing IONOS builder/API permissions is a blocker. Do not work around with public-read rule changes. IONOS's November 13 statement does not guarantee this API is available, so the tool is a conditional recovery path, not proof that it can be executed on NIJA's account.

## Release safety

- Keep sending OFF, unpublished pending fixes unreleased, and historical QA/existing uncertain claims held.
- Existing verified Render point-in-time recovery (87 intake, 87 CRM, 12 forwarding) remains separate and must be retained.
- Verify receipt-create rules, published hook location and current admin/builder revision; require independent review, source/build parity and required security checks before a separately approved lead-only release.
- After full off-host restoration proof, independently verify published Zap 378270777 URL/event mapping, one server sender, webhook/auth secrets, destination Apollo identity, Resend acceptance, and consent; then obtain separate approval for one nonmarketing LIVE QA and duplicate-retry test.
- No payment, billing, trading, DNS, customer-contact, deployment, IONOS authorization or privileged database write is permitted by this document.