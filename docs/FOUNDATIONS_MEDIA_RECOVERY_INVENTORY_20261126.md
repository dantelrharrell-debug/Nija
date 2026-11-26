# Trading Foundations media recovery inventory — 2026-11-26

Status: **NOT CERTIFIED FOR VIDEO DELIVERY**. This is a read-only evidence ledger, not an approval to publish, upload, charge, or change access.

## Evidence located

| Source | Item | Observed size | Classification |
| --- | --- | ---: | --- |
| Google Drive `1vgSWJh3aZzXh8b4Fdl5goVQwFTgNl1-H` | NIJA_ElevenLabs_Full_Audiobook_Script.txt | 38,790 bytes | Script only; not finished audio/video |
| Google Drive `1uscUZsTXm0YWFfvwtQSvt6eqlmuKAphR` | NIJA_ElevenLabs_Audiobook_Script_ONLY.txt | 38,790 bytes | Script copy; byte identity unverified |
| Google Drive `195gHUT_SJIK0zHgWsU4WECQ4zaoJBfHS` | NIJA_ElevenLabs_Full_Audiobook_Script.txt | 38,790 bytes | Script copy; byte identity unverified |
| Google Drive `1q1lrwFm5lZxJ_b9DGp7MAYfLCGS5tAAm` | NIJA_12_Week_Trading_Practice_Journal.pdf | 1,060,399 bytes | Supporting PDF; hash not checked |
| Google Drive `1_TV7f2YUqt9UKD23_da_Q5TdeWm7HcKH` | NIJA_12_Week_Trading_Practice_Journal.pdf | 1,060,399 bytes | Supporting PDF copy; hash not checked |
| Google Docs `1qiCfwrLnhPSA6jUOso4wpvW2yniZBVfG5ZKNxcYLx5c` | Expanded Trading Discipline Workbook — Sample Draft | — | Draft, not approved course deliverable |

Drive MIME searches for `video/` and `audio/` returned no results within the connected account. This is not proof that no originals exist elsewhere.

## Repository package records

`course_portal.py` declares an expected customer package with a final MP3 audiobook and seven PDFs: video/audiobook scripts, certificate, journal, workbook, Start Here, Starter Kit and eBook. Its `ALLOWED` mapping pins expected SHA-256 values, **not evidence that these originals were fetched or verified today**. Existing private ZIP/PDF/MP3 handling is separate from optional MP4 streaming.

## Video manifest and release hold

No finished MP4 originals were verified. Accordingly **no approved video manifest entries exist**. Do not set `NIJA_COURSE_VIDEO_ROOT` or `NIJA_COURSE_VIDEO_MANIFEST_SHA256` using a placeholder or empty manifest. Do not activate the video catalog.

For each independently approved original, capture: lesson ID, exact title, curriculum position, original location, file size in bytes, SHA-256, owner approval, codec/container validation, and any transcode provenance. Only then create `manifest.json` with `id`, `title`, `sha256`, `size_bytes`, using immutable `<sha256>.mp4` delivery names. Pin the SHA-256 of the manifest separately.

Follow `docs/FOUNDATIONS_PRIVATE_VIDEO_DELIVERY.md` for private read-only durable storage and isolated verification: catalog hash, GET/HEAD/range seeking, mobile Safari, signed-out and non-entitled denial, refund/revocation (including a new seek), no-store headers, restart durability, rollback. Never place paid masters in GitHub, public paths, ephemeral Render storage or billing Postgres.

## iPad recovery

In iPad Files > Browse, inspect On My iPad, iCloud Drive, Downloads and connected providers; search NIJA, Foundations, .mp4, .mov, .mp3. Check Photos and editor exports (CapCut/iMovie). Supply original filenames and storage locations or attach candidate originals privately for verification. Do not publish or transfer masters into a public folder.

## Outstanding gates

- [ ] Owner-approved ordered lesson list and finished MP4 masters
- [ ] Independent size/SHA-256 verification for each video
- [ ] Verify final audiobook and package PDF originals against existing pinned hashes
- [ ] Approved durable private read-only storage, separately deployable
- [ ] Isolated entitlement/playback/seek/revocation and restart acceptance
- [ ] Separate release approval before any production settings or customer-access change
