"""Offline course video delivery, using no provider credentials or requests."""
import hashlib
import json
import os
import stat
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import BoundedSemaphore, Event

import pytest

BASE = "https://localhost"
LESSON = "/course-portal/video/lesson-01"


@pytest.fixture
def context(tmp_path, monkeypatch):
    import billing_service as billing
    import course_portal as portal
    import course_private_video as private
    from billing_service_store import BillingServiceStore

    root = tmp_path / "private"
    root.mkdir()
    dummy = os.getenv("NIJA_SYNTHETIC_TEST_MP4")
    payload = Path(dummy).read_bytes() if dummy else b"synthetic media bytes for seek test" * 10
    sha = hashlib.sha256(payload).hexdigest()
    media = root / (sha + ".mp4")
    media.write_bytes(payload)
    item = {"id": "lesson-01", "title": "Lesson & Introduction", "size_bytes": len(payload), "sha256": sha}
    manifest = root / "manifest.json"
    raw = json.dumps([item]).encode()
    manifest.write_bytes(raw)
    url = f"sqlite:///{tmp_path / 'billing.db'}"
    monkeypatch.setenv("BILLING_DATABASE_URL", url)
    monkeypatch.setenv("NIJA_COURSE_DELIVERY_ENABLED", "true")
    monkeypatch.setenv("NIJA_COURSE_SESSION_SECRET", "synthetic-session-secret-" * 3)
    monkeypatch.setenv("NIJA_COURSE_VIDEO_ROOT", str(root))
    monkeypatch.setenv("NIJA_COURSE_VIDEO_MANIFEST_SHA256", hashlib.sha256(raw).hexdigest())
    # The production root guard is tested independently; the fixture is disposable.
    monkeypatch.setattr(private, "_allowed_root", lambda candidate: candidate == root)
    monkeypatch.setattr(private, "_mount_is_readonly", lambda fd: True)
    monkeypatch.setattr(portal.PortalStore, "has_bundle", lambda self: True)
    # Exercise real cookie verification and request path; replace only provider evidence.
    paid = {"cs_test_paid": {"customer_email": "synthetic@example.invalid"}}
    monkeypatch.setattr(portal, "_valid_paid", paid.get)
    app = billing.create_app(BillingServiceStore(url))
    client = app.test_client()

    def sign(sid="cs_test_paid", email="synthetic@example.invalid"):
        token = portal._signer().dumps({"sid": sid, "email": email})
        client.set_cookie(portal.COOKIE, token, path="/course-portal", secure=True)

    return client, sign, paid, root, item, media, payload


def test_signed_out_and_nonentitled_video_denials(context):
    client, sign, *_ = context
    for headers in ({}, {"Range": "bytes=0-7"}):
        assert client.get(LESSON, base_url=BASE, headers=headers).status_code == 403
    sign(sid="cs_test_other")
    assert client.get(LESSON, base_url=BASE).status_code == 403
    sign(email="mismatch@example.invalid")
    assert client.get(LESSON, base_url=BASE).status_code == 403


def test_entitled_get_head_and_video_seek(context, tmp_path):
    client, sign, _, _, _, _, payload = context
    sign()
    for headers, code, expected in (({}, 200, payload), ({"Range": "bytes=8-19"}, 206, payload[8:20])):
        with client.get(LESSON, base_url=BASE, headers=headers) as result:
            assert result.status_code == code
            assert result.mimetype == "video/mp4"
            assert result.headers["Cache-Control"] == "private, no-store"
            assert result.headers["Accept-Ranges"] == "bytes"
            assert result.data == expected
            if code == 200:
                (tmp_path / "served.mp4").write_bytes(result.data)
            else:
                assert result.headers["Content-Range"] == f"bytes 8-19/{len(payload)}"
    with client.head(LESSON, base_url=BASE) as result:
        assert result.status_code == 200 and result.data == b""
        assert result.content_length == len(payload)
    assert client.get(LESSON, base_url=BASE, headers={"Range": f"bytes={len(payload)}-"}).status_code == 416
    html = client.get("/course-portal/library", base_url=BASE).get_data(as_text=True)
    assert "Lesson &amp; Introduction" in html and LESSON in html
    assert "/static/course/" not in html


def test_video_revocation_applies_before_next_seek(context):
    client, sign, paid, *_ = context
    sign()
    with client.get(LESSON, base_url=BASE, headers={"Range": "bytes=0-7"}) as result:
        assert result.status_code == 206
    paid.clear()
    assert client.get(LESSON, base_url=BASE, headers={"Range": "bytes=8-19"}).status_code == 403


def test_unpinned_manifest_or_unknown_lesson_stays_closed(context, monkeypatch):
    client, sign, *_ = context
    sign()
    assert client.get("/course-portal/video/unknown", base_url=BASE).status_code == 404
    monkeypatch.setenv("NIJA_COURSE_VIDEO_MANIFEST_SHA256", "0" * 64)
    assert client.get(LESSON, base_url=BASE).status_code == 404
    assert client.get("/course-portal/library", base_url=BASE).status_code == 200


def test_unverified_files_do_not_pass_staging_inventory(context):
    from course_private_video import verify_video_inventory
    client, sign, _, root, item, media, payload = context
    sign()
    assert verify_video_inventory(root, {"lesson-01": item}) == 1
    media.write_bytes(b"x" * len(payload))
    with pytest.raises(ValueError, match="digest"):
        verify_video_inventory(root, {"lesson-01": item})
    media.unlink()
    target = root / "target"
    target.write_bytes(payload)
    media.symlink_to(target)
    assert client.get(LESSON, base_url=BASE).status_code == 404


def test_runtime_catalog_rejects_application_root_and_system_temp():
    from course_private_video import _allowed_root
    import course_private_video
    assert not _allowed_root(Path(course_private_video.__file__).resolve().parent)
    assert not _allowed_root(Path("/tmp"))


def test_entitled_requests_do_not_serve_a_writable_store(context, monkeypatch):
    import course_private_video as private

    client, sign, _, _, _, media, payload = context
    sign()
    monkeypatch.setattr(private, "_mount_is_readonly", lambda fd: False)
    media.write_bytes(b"x" * len(payload))
    assert private.configured_catalog() == (None, {})
    assert client.get(LESSON, base_url=BASE, headers={"Range": "bytes=0-7"}).status_code == 404
    assert client.get("/course-portal/library", base_url=BASE).status_code == 200


def test_readonly_catalog_does_not_authorize_a_writable_child_media_mount(context, monkeypatch):
    import course_private_video as private

    client, sign, _, root, item, _, _ = context
    sign()
    def is_catalog_entry(fd):
        return os.fstat(fd).st_ino == (root / "manifest.json").stat().st_ino

    monkeypatch.setattr(private, "_mount_is_readonly", lambda fd: (
        stat.S_ISDIR(os.fstat(fd).st_mode) or is_catalog_entry(fd)
    ))
    assert private.configured_catalog()[1] == {"lesson-01": item}
    assert client.get(LESSON, base_url=BASE, headers={"Range": "bytes=0-7"}).status_code == 404


def test_mount_gate_rejects_chmod_as_substitute_for_readonly_filesystem(tmp_path):
    from course_private_video import _mount_is_readonly

    file = tmp_path / "readonly-permissions"
    file.write_bytes(b"fixture")
    file.chmod(0o444)
    with file.open("rb") as opened:
        assert not _mount_is_readonly(opened.fileno())


@pytest.fixture
def fake_object_origin(context, monkeypatch):
    """Exercise the portal with an injected immutable origin, never real storage."""
    from flask import Response, request
    from werkzeug.http import parse_range_header

    monkeypatch.setenv("NIJA_BILLING_IDENTITY_SECRET", "synthetic-fixture-" * 3)

    import course_portal as portal

    client, sign, paid, root, item, _, payload = context
    version = "fixture-immutable-version"
    sha = hashlib.sha256(payload).hexdigest()
    objects = {(sha, version): payload}
    calls = []
    occupied = Event()
    release = Event()
    hold_seek = Event()
    slot = BoundedSemaphore(1)

    def fake_response(catalog_root, entry):
        assert catalog_root == root
        if not slot.acquire(blocking=False):
            return Response(status=503, headers={"Retry-After": "1", "Cache-Control": "private, no-store"})
        try:
            data = objects.get((entry["sha256"], version))
            calls.append((request.method, request.headers.get("Range")))
            if data is None or len(data) != entry["size_bytes"]:
                raise ValueError("fixture_object_unavailable")
            if hashlib.sha256(data).hexdigest() != entry["sha256"]:
                raise ValueError("fixture_object_digest_mismatch")
            headers = {"Cache-Control": "private, no-store", "Accept-Ranges": "bytes"}
            if request.method == "HEAD" or not request.headers.get("Range"):
                response = Response(data if request.method != "HEAD" else b"",
                                    mimetype="video/mp4", headers=headers)
                response.content_length = len(data)
                return response
            parsed = parse_range_header(request.headers["Range"])
            bounds = parsed.range_for_length(len(data)) if parsed is not None else None
            if bounds is None:
                headers["Content-Range"] = f"bytes */{len(data)}"
                return Response(status=416, headers=headers)
            start, end = bounds
            if hold_seek.is_set():
                occupied.set()
                if not release.wait(timeout=5):
                    raise ValueError("fixture_seek_deadline")
            headers["Content-Range"] = f"bytes {start}-{end - 1}/{len(data)}"
            return Response(data[start:end], status=206, mimetype="video/mp4", headers=headers)
        finally:
            slot.release()

    monkeypatch.setattr(portal, "video_response", fake_response)
    return client, sign, paid, payload, objects, calls, occupied, release, hold_seek


def test_object_rehearsal_entitlement_head_seek_and_revocation(fake_object_origin):
    client, sign, paid, payload, _, calls, *_ = fake_object_origin
    assert client.get(LESSON, base_url=BASE).status_code == 403
    assert client.head(LESSON, base_url=BASE).status_code == 403
    assert calls == []
    sign()
    whole = client.get(LESSON, base_url=BASE)
    assert whole.status_code == 200 and whole.data == payload
    head = client.head(LESSON, base_url=BASE)
    assert head.status_code == 200 and head.data == b"" and head.content_length == len(payload)
    seek = client.get(LESSON, base_url=BASE, headers={"Range": "bytes=-5"})
    assert seek.status_code == 206 and seek.data == payload[-5:]
    assert seek.headers["Cache-Control"] == "private, no-store"
    assert seek.headers["Content-Range"] == f"bytes {len(payload) - 5}-{len(payload) - 1}/{len(payload)}"
    bad = client.get(LESSON, base_url=BASE, headers={"Range": "bytes=0-2,5-7"})
    assert bad.status_code == 416 and bad.headers["Content-Range"] == f"bytes */{len(payload)}"
    n = len(calls)
    paid.clear()
    assert client.get(LESSON, base_url=BASE, headers={"Range": "bytes=0-7"}).status_code == 403
    assert len(calls) == n


def test_object_rehearsal_missing_and_changed_bytes_do_not_serve(fake_object_origin):
    client, sign, _, payload, objects, *_ = fake_object_origin
    sign()
    key = next(iter(objects))
    objects[key] = b"x" * len(payload)
    changed = client.get(LESSON, base_url=BASE, headers={"Range": "bytes=0-7"})
    assert changed.status_code == 404 and changed.json["error"] == "asset_not_available"
    objects.clear()
    assert client.get(LESSON, base_url=BASE).status_code == 404


def test_object_rehearsal_keeps_a_worker_slot_for_health_and_checkout(fake_object_origin):
    from course_portal import COOKIE

    client, sign, _, payload, _, calls, occupied, release, hold_seek = fake_object_origin
    sign()
    app = client.application
    cookie = client.get_cookie(COOKIE, path="/course-portal")
    assert cookie is not None
    hold_seek.set()

    def make_request(method, path, **kwargs):
        with app.test_client() as separate_client:
            separate_client.set_cookie(COOKIE, cookie.value, path="/course-portal", secure=True)
            return separate_client.open(path, method=method, base_url=BASE, **kwargs)

    with ThreadPoolExecutor(2) as requests:
        first = requests.submit(make_request, "GET", LESSON, headers={"Range": "bytes=0-31"})
        try:
            assert occupied.wait(timeout=3)
            second = requests.submit(make_request, "GET", LESSON, headers={"Range": "bytes=32-63"})
            rejected = second.result(timeout=2)
            assert rejected.status_code == 503 and rejected.headers["Retry-After"] == "1"
            # Checkout reaches its real request/authentication gate without a provider call.
            assert requests.submit(make_request, "POST", "/api/billing/checkout", json={}).result(
                timeout=2
            ).status_code == 401
            assert requests.submit(make_request, "GET", "/healthz").result(timeout=2).status_code == 200
            assert len(calls) == 1
        finally:
            release.set()
        result = first.result(timeout=2)
        assert result.status_code == 206 and result.data == payload[:32]


def test_pinned_s3_versions_through_buyer_route(context, monkeypatch):
    from base64 import b64encode
    from contextlib import nullcontext
    from io import BytesIO
    from botocore.response import StreamingBody
    from course_private_video import configured_catalog, verify_video_inventory
    from course_video_object import ObjectSource

    client, sign, paid, _, item, _, payload = context
    item["version"] = "immutable-fixture-v1"
    manifest = json.dumps([item])
    monkeypatch.setenv("NIJA_COURSE_S3_BUCKET", "course-fixture")
    monkeypatch.setenv("NIJA_COURSE_OBJECT_MANIFEST", manifest)
    monkeypatch.setenv("NIJA_COURSE_VIDEO_MANIFEST_SHA256", hashlib.sha256(manifest.encode()).hexdigest())
    expected = dict(Bucket="course-fixture", VersionId=item["version"], Key=f"foundations/{item['sha256']}.mp4")
    calls = []
    checksum = b64encode(hashlib.sha256(payload).digest()).decode()

    class Origin:
        def head_object(self, **params):
            assert params == {**expected, "ChecksumMode": "ENABLED"}
            calls.append("head")
            return dict(VersionId=item["version"], ContentLength=len(payload), ChecksumSHA256=checksum)

        def get_object(self, **params):
            interval = params.pop("Range", None)
            assert params == expected
            calls.append("get")
            data = payload
            reply = {}
            if interval:
                assert interval == "bytes=2-6"
                data = payload[2:7]
                reply["ContentRange"] = f"bytes 2-6/{len(payload)}"
            return dict(reply, VersionId=item["version"], ContentLength=len(data),
                        Body=StreamingBody(BytesIO(data), len(data)))

    monkeypatch.setattr(ObjectSource, "_client", lambda self: nullcontext(Origin()))
    assert client.head(LESSON, base_url=BASE).status_code == 403
    assert not calls
    assert verify_video_inventory(*configured_catalog()) == 1
    sign()
    with client.head(LESSON, base_url=BASE) as head:
        assert head.status_code == 200 and head.content_length == len(payload) and not head.data
    with client.get(LESSON, base_url=BASE, headers={"Range": "bytes=2-6"}) as partial:
        assert partial.status_code == 206 and partial.data == payload[2:7]
        assert partial.headers["Content-Range"] == f"bytes 2-6/{len(payload)}"
        assert client.head(LESSON, base_url=BASE).status_code == 503
    with client.get(LESSON, base_url=BASE) as whole:
        assert whole.status_code == 200 and whole.data == payload
    checksum = "mismatched"
    assert client.get(LESSON, base_url=BASE).status_code == 404
    paid.clear()
    n = len(calls)
    assert client.head(LESSON, base_url=BASE).status_code == 403 and len(calls) == n
