# Foundations private lesson playback (preview candidate)

No storage provider is provisioned by this change. The current course portal, checkout,
downloads and customer entitlements are unchanged without both video settings below.
Do not use public static paths, a source repository, or an ephemeral Render filesystem
for paid masters. Do not upload to billing Postgres as a substitute for streaming storage.

## Prepare the private source

Select an approved durable store with a private, read-only runtime mount. The portal
service and content must be separately deployable and the portal process must not be
able to modify the mount. Never operate the origin as a public file server. If the
selected durable store is object storage without a supported private mount, implement
and test its authenticated range adapter separately; this change does not connect it.

On a trusted staging device, match the exact owner-approved lesson inventory and record
bytes and SHA-256 for each original. Use H.264/AAC seeking-compatible MP4 as needed,
keeping originals untouched. Name verified delivery files <sha256>.mp4. Create
manifest.json, a JSON array with id, title, sha256 and size_bytes for each lesson.
Pin the manifest SHA-256 separately. Set NIJA_COURSE_VIDEO_ROOT to the canonical
absolute private mount and NIJA_COURSE_VIDEO_MANIFEST_SHA256 to the manifest hash.
The mount must not be underneath the app tree or system temporary paths. Verify in the
target host, before any release:

```sh
python -c 'from course_private_video import configured_catalog, verify_video_inventory; print("Verified videos:", verify_video_inventory(*configured_catalog()))'
```

Require every intended paid file to match and the portal worker's actual filesystem
mount to be read-only. Changing POSIX permissions alone is not sufficient. The
portal rejects writable mount descriptors for the root, manifest, or media file. The
operator inventory check cryptographically verifies file bytes; runtime rechecks
the pinned manifest, file type, size, and read-only mount flags per request. Keep
the underlying storage immutable to other writers; a read-only portal bind alone
does not prevent out-of-band replacement via a different writable mount. Do not enable the route with mutable public storage.

## Acceptance and rollback

In the isolated sandbox, verify test-account entitlements and exact media inventory.
Test GET, HEAD and seeking with clean mobile Safari and desktop sessions; deny signed-out,
non-entitled, invalid and refunded access, including a new seek after revocation. Ensure
the endpoint returns a private no-store response, and check ordinary downloads, checkout
handoff and recovery remain unchanged. Confirm provider readback latency and request
capacity during simultaneous video seeks; there is no authorization cache or signed
public link to bypass live entitlement checks. Test restart and media durability.

After a separately approved rollout and positive entitled playback, retire old public
copies and verify public denial on the previous URLs. Preserve private masters, historical
payments, earlier entitlements and the existing recovery path. Rollback disables the
optional catalog by removing its two settings; do not re-expose retired media or restore
the retired ClickBank browser grant. No new live settings, billing or IONOS publish is
included in this change.
