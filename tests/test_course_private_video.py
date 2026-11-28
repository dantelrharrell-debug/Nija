"""Offline course video delivery, using no provider credentials or requests."""
import hashlib
import json
import os
import stat
from pathlib import Path

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
