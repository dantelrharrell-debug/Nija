"""Authenticated reads of pinned Amazon S3 object versions for the course portal."""
import base64
import hashlib
import os
import re
from contextlib import ExitStack, closing
from dataclasses import dataclass
from threading import BoundedSemaphore

from flask import Response, request
from werkzeug.http import parse_range_header

_stream_slot = BoundedSemaphore(1)


@dataclass(frozen=True)
class ObjectSource:
    """Read only content-addressed objects, always using an explicit version."""

    bucket: str

    @staticmethod
    def valid_version(value: object) -> bool:
        """Reject missing or mutable null versions."""
        return isinstance(value, str) and value != "null" and bool(re.fullmatch(r"[!-~]{1,1024}", value))

    def _client(self):
        import botocore.session
        from botocore.config import Config

        region = os.getenv("NIJA_COURSE_S3_REGION", "")
        key = os.getenv("NIJA_COURSE_S3_ACCESS_KEY_ID")
        secret = os.getenv("NIJA_COURSE_S3_SECRET_ACCESS_KEY")
        if not (re.fullmatch(r"[a-z]{2}(?:-[a-z0-9]+)+-\d+", region) and key and secret
                and re.fullmatch(r"[a-z0-9][a-z0-9-]{1,61}[a-z0-9]", self.bucket)):
            raise ValueError("private_object_configuration_invalid")
        return botocore.session.get_session().create_client(
            "s3", region_name=region, endpoint_url=f"https://s3.{region}.amazonaws.com",
            aws_access_key_id=key, aws_secret_access_key=secret,
            aws_session_token=os.getenv("NIJA_COURSE_S3_SESSION_TOKEN"),
            config=Config(connect_timeout=3, read_timeout=10, retries={"total_max_attempts": 2}),
        )

    def _params(self, entry):
        return dict(Bucket=self.bucket, Key=f"foundations/{entry['sha256']}.mp4", VersionId=entry["version"])

    def _head(self, client, entry):
        head = client.head_object(**self._params(entry), ChecksumMode="ENABLED")
        checksum = base64.b64encode(bytes.fromhex(entry["sha256"])).decode("ascii")
        if (head.get("VersionId") != entry["version"] or head.get("ContentLength") != entry["size_bytes"]
                or head.get("ChecksumSHA256") != checksum):
            raise ValueError("private_object_integrity_mismatch")

    def verify(self, entry: dict) -> None:
        """Independently hash the full immutable version during inventory verification."""
        from botocore.exceptions import BotoCoreError, ClientError

        try:
            with self._client() as client:
                self._head(client, entry)
                result = client.get_object(**self._params(entry))
                with closing(result["Body"]) as body:
                    if (result.get("VersionId") != entry["version"] or result.get("ContentLength") != entry["size_bytes"]):
                        raise ValueError("private_object_integrity_mismatch")
                    digest = hashlib.sha256()
                    for chunk in body.iter_chunks(64 * 1024):
                        digest.update(chunk)
                    if digest.hexdigest() != entry["sha256"]:
                        raise ValueError("private_object_digest_mismatch")
        except (BotoCoreError, ClientError) as exc:
            raise ValueError("private_object_unavailable") from exc

    def response(self, entry: dict) -> Response:
        """Stream one authenticated request while reserving capacity for billing."""
        from botocore.exceptions import BotoCoreError, ClientError

        size = entry["size_bytes"]
        headers = {"Cache-Control": "private, no-store", "Accept-Ranges": "bytes", "Content-Disposition": "inline"}
        args = self._params(entry)
        span = None
        if "Range" in request.headers:
            ranges = parse_range_header(request.headers["Range"])
            span = ranges.range_for_length(size) if ranges else None
            if not span:
                return Response(status=416, headers={**headers, "Content-Range": f"bytes */{size}"})
            start, stop = span
            args["Range"] = f"bytes={start}-{stop - 1}"
            headers["Content-Range"] = f"bytes {start}-{stop - 1}/{size}"
        length = span[1] - span[0] if span else size
        headers["Content-Length"] = str(length)
        if not _stream_slot.acquire(blocking=False):
            return Response(status=503, headers={"Retry-After": "1", "Cache-Control": "private, no-store"})

        with ExitStack() as stack:
            stack.callback(_stream_slot.release)
            try:
                client = stack.enter_context(self._client())
                self._head(client, entry)
                if request.method == "HEAD":
                    response = Response(status=206 if span else 200, headers=headers, mimetype="video/mp4")
                else:
                    obj = client.get_object(**args)
                    body = stack.enter_context(closing(obj["Body"]))
                    if (obj.get("VersionId") != entry["version"] or obj.get("ContentLength") != length
                            or obj.get("ContentRange") != headers.get("Content-Range")):
                        raise ValueError("private_object_response_mismatch")
                    response = Response(body.iter_chunks(64 * 1024), status=206 if span else 200,
                                        headers=headers, mimetype="video/mp4")
                    response.call_on_close(stack.pop_all().close)
                response.content_length = length
                return response
            except (BotoCoreError, ClientError) as exc:
                raise ValueError("private_object_unavailable") from exc


def object_catalog_source() -> ObjectSource | None:
    """Use versioned storage only when a course bucket is explicitly selected."""
    bucket = os.getenv("NIJA_COURSE_S3_BUCKET")
    return ObjectSource(bucket) if bucket else None
