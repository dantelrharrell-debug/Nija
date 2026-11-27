#!/usr/bin/env python3
"""Read-only, redacted public NIJA privacy and paid-file access verification.

Sensitive paid URLs come from a private local JSON manifest. Do not check them
into GitHub or paste them into tickets. No customer bytes or URL values are
logged or preserved. A pass is NOT authenticated purchaser-delivery proof.
"""
from __future__ import annotations

import argparse
import html
import json
from pathlib import Path
import re
from typing import Any
import urllib.error
import urllib.parse
import urllib.request

PAGE_BYTES = 512 * 1024
DENIED = {401, 403, 404, 410}


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


OPENER = urllib.request.build_opener(_NoRedirect)


def _read_status(url: str, method: str, limit: int = 0) -> tuple[int, bytes]:
    headers = {"User-Agent": "NIJA-Privacy-ReadOnly-Acceptance/1.0",
               "Cache-Control": "no-cache"}
    if method == "GET" and limit == 16:
        headers["Range"] = "bytes=0-15"
    request = urllib.request.Request(url, method=method, headers=headers)
    try:
        with OPENER.open(request, timeout=12) as response:
            return response.status, response.read(limit)
    except urllib.error.HTTPError as error:
        with error:
            return error.code, error.read(limit)


def _visible(source: bytes) -> str:
    text = source.decode("utf-8", errors="replace")
    text = re.sub(r"(?is)<(script|style)\b[^>]*>.*?</\1\s*>", " ", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", html.unescape(text)).strip().lower()


def evaluate_policy(status: int, body: bytes) -> tuple[bool, str]:
    if status != 200:
        return False, "policy_http_not_200"
    text = _visible(body)
    if any(term in text for term in (
            "full policy pending", "full approved privacy policy is pending",
            "comprehensive privacy policy covering all data collection",
            "pending owner approval", "lorem ipsum")):
        return False, "policy_placeholder"
    if not all(term in text for term in ("privacy", "retention", "account", "request")):
        return False, "policy_missing_core_topics"
    if not re.search(r"\b20\d{2}-\d{2}-\d{2}\b", text):
        return False, "policy_effective_date_unverified"
    return True, "policy_content_candidate_only"


def evaluate_deletion(status: int, body: bytes) -> tuple[bool, str]:
    if status != 200:
        return False, "deletion_http_not_200"
    text = _visible(body)
    if "this page doesn't exist" in text or "page not found" in text:
        return False, "deletion_site_404"
    if not all(term in text for term in ("delete", "account", "support", "not cover")):
        return False, "deletion_scope_or_contact_missing"
    return True, "deletion_content_candidate_only"


def evaluate_private(head: int, range_get: int) -> tuple[bool, str]:
    if head in DENIED and range_get in DENIED:
        return True, "anonymous_access_denied"
    if head in (200, 206) or range_get in (200, 206):
        return False, "anonymous_asset_accessible"
    return False, "asset_access_unverified"


def evaluate_free(head: int, range_get: int, prefix: bytes) -> tuple[bool, str]:
    if head not in (200, 206) or range_get not in (200, 206):
        return False, "free_asset_unavailable"
    if not prefix.startswith(b"%PDF-"):
        return False, "free_asset_signature_mismatch"
    return True, "free_starter_pdf_accessible"


def _same_origin(site: str, value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("empty_asset_reference")
    root = urllib.parse.urlsplit(site)
    if root.scheme != "https" or not root.hostname or root.username or root.password:
        raise ValueError("invalid_site_origin")
    url = urllib.parse.urlsplit(urllib.parse.urljoin(site + "/", value))
    if (url.scheme != "https" or url.netloc != root.netloc or url.username
            or url.password or url.query or url.fragment):
        raise ValueError("asset_not_same_origin_or_contains_query")
    return urllib.parse.urlunsplit(url)


def _manifest(path: Path, site: str) -> list[str]:
    values: Any = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(values, list) or not 1 <= len(values) <= 200:
        raise ValueError("manifest_requires_1_to_200_entries")
    urls = [_same_origin(site, value) for value in values]
    if len(set(urls)) != len(urls):
        raise ValueError("duplicate_asset_reference")
    return urls


def verify(site: str, manifest: Path | None, free_path: str | None) -> dict[str, Any]:
    site = site.rstrip("/")
    _same_origin(site, "/")
    pages: dict[str, Any] = {}
    for name, path, evaluator in (
            ("policy", "/privacy-policy", evaluate_policy),
            ("deletion", "/account-deletion", evaluate_deletion)):
        try:
            status, excerpt = _read_status(site + path, "GET", PAGE_BYTES)
            ok, reason = evaluator(status, excerpt)
        except (OSError, TimeoutError, ValueError):
            ok, reason = False, "page_request_failed"
        pages[name] = {"pass": ok, "reason": reason}

    private: dict[str, Any] = {
        "status": "not_tested", "count": 0, "denied": 0, "failures": 0}
    if manifest:
        urls = _manifest(manifest, site)
        private.update({"status": "tested", "count": len(urls)})
        for url in urls:
            try:
                head, _ = _read_status(url, "HEAD")
                partial, _ = _read_status(url, "GET", 16)
                ok, _ = evaluate_private(head, partial)
            except (OSError, TimeoutError, ValueError):
                ok = False
            private["denied" if ok else "failures"] += 1

    free: dict[str, Any] = {"status": "not_tested"}
    if free_path:
        url = _same_origin(site, free_path)
        try:
            head, _ = _read_status(url, "HEAD")
            partial, prefix = _read_status(url, "GET", 16)
            ok, reason = evaluate_free(head, partial, prefix)
        except (OSError, TimeoutError, ValueError):
            ok, reason = False, "free_asset_request_failed"
        free = {"status": "tested", "pass": ok, "reason": reason}

    page_ok = all(item["pass"] for item in pages.values())
    private_ok = private["status"] == "tested" and not private["failures"]
    free_ok = free["status"] == "tested" and free.get("pass", False)
    if (not page_ok or (private["status"] == "tested" and not private_ok)
            or (free["status"] == "tested" and not free_ok)):
        result = "fail"
    elif private_ok and free_ok:
        result = "public_checks_passed_purchaser_access_not_tested"
    else:
        result = "partial_only_untested_assets_or_free_kit"
    return {"outcome": result, "pages": pages, "private_assets": private,
            "free_starter_kit": free, "authorized_purchaser_access": "not_tested"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site", default="https://nijaaitrading.com")
    parser.add_argument("--private-manifest", type=Path)
    parser.add_argument("--free-url", help="Verified same-origin path to free PDF")
    args = parser.parse_args()
    try:
        result = verify(args.site, args.private_manifest, args.free_url)
    except (ValueError, OSError, json.JSONDecodeError):
        result = {"outcome": "failed_to_validate_private_inputs"}
    print(json.dumps(result, sort_keys=True))
    if result.get("outcome") == "fail":
        return 1
    if result.get("outcome") != "public_checks_passed_purchaser_access_not_tested":
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
