# NIJA website privacy / paid-asset acceptance — review packet

Prepared November 27, 2026. **Source-only and read-only, NOT production-certified or approved legal copy.**

The merged GitHub privacy drafts do not publish NIJA's IONOS AI Site Builder website. Anonymous checks on November 27 found the live /privacy-policy still labeled FULL POLICY PENDING and /account-deletion showing a site 404. Previously reported paid/internal public course files require fresh access testing and confirmation of private originals.

## Required containment and publication

1. Identify the correct **owner-authenticated** IONOS AI Builder project `aibuilder-4dfdf` and exact live published version before any changes. IONOS documents access via Menu > Web Projects > Manage project. The precise editor for this project still needs confirmation.
2. Inventory and privately preserve original paid lesson assets, internal files, entitlements and free NIJA_Starter_Kit.pdf. Do not paste sensitive paid URL lists into public repositories, issues or support emails.
3. Deny anonymous GET, HEAD and Range requests for the affected public paid/internal copies, including CDN/cache copies, without removing private originals or restricting the free Starter Kit. If precise restriction is unsupported, STOP before deleting a whole directory or publishing a destructive version; obtain exact owner approval.
4. Use the corrected [source Privacy Policy](../PRIVACY_POLICY.md) and [deletion-scope instructions](../mobile/ACCOUNT_DELETION.md) only as review material. Get owner/legal approval of the specific public text, effective date, privacy contact, actual recipient and retention disclosures, age eligibility, consent flows and limited deletion claim. Do not invent data retention periods or full erasure claims.
5. Preview, preserve a rollback/version, and publish **only approved** revisions to /privacy-policy and /account-deletion. After publishing, independently test the page text, mobile presentation, privacy contact links, expired JWT rejection in each deployed gateway, anonymous asset access, free Starter Kit and authenticated purchaser delivery separately.

IONOS source references:
- https://www.ionos.com/help/websites-stores/organize-websites-and-stores/logging-in-to-your-website-builder/
- https://www.ionos.com/help/websites-stores/organize-websites-and-stores/using-the-website-builder-after-december-2024/

The second IONOS article describes Webspace Explorer for **certain** Website Builder projects. It does not verify that NIJA's specific AI Site Builder assets live there.

## Read-only verifier

The standard-library-only script `scripts/check_public_privacy_access.py` checks the public policy placeholder and deletion 404 without authentication. It does not fix or deploy either page.

Command: `python scripts/check_public_privacy_access.py`

To also verify private paid files and the free PDF, supply an **owner-held local JSON manifest OUTSIDE Git** containing 1–200 unique actual same-origin paths and the real free file path:

```sh
python scripts/check_public_privacy_access.py --private-manifest /private/paid-paths.json --free-url /VERIFIED_FREE_PATH/NIJA_Starter_Kit.pdf
```

The manifest example `["/private/synthetic.mp4"]` is fictitious; never enter real paths in a public PR. The script sends bounded GET/HEAD requests, refuses redirects, records only aggregate success/failure, and treats any anonymous 2xx response to paid content as a failure. For paid/internal files it requires denial of HEAD, ordinary GET and Range GET, without reading paid response bodies. The free PDF must remain readable and have a PDF signature.

Exit code `0`: all *public-only* probes passed; purchaser entitlement remains UNTESTED. Exit `1`: failed public test. Exit `2`: partial input or result; do not certify. Provider failures and uncertain redirects fail closed.

Record the exact UTC time, approved operator, IONOS published revision, asset-category counts without secret paths, private backup custody, post-change anonymous tests, free-PDF result, authenticated customer-access proof, effective date and independent reviewer signoff. Track open conditions in [#4204](https://github.com/dantelrharrell-debug/Nija/issues/4204) and security in [#3970](https://github.com/dantelrharrell-debug/Nija/issues/3970).
