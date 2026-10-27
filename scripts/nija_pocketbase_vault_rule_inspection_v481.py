"""Restricted read-only PocketBase collection rule inspection for NIJA.

Invoke ONLY from an operator-controlled environment holding a short-lived,
legitimate PocketBase superuser token. No login, credential capture, writes,
collection changes, or health/readiness-flag promotion are performed.
The IONOS-admin OAuth gateway is not bypassed by this diagnostic.
"""
from __future__ import annotations

import json
import os
import re
import sys
from collections.abc import Mapping
from urllib import error, parse, request

HOST = "nijaaitrading.com"
API_ROOT = "https://" + HOST + "/.sfs-be/api/collections/"
MAX_BYTES = 65536


class AuditDenied(ValueError):
    """Fixed diagnostic label; no tokens or private server response text."""


class _NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _canonical(base_url: str) -> str:
    if not isinstance(base_url, str):
        raise AuditDenied("origin_invalid")
    try:
        parsed = parse.urlsplit(base_url)
        port = parsed.port
    except ValueError:
        raise AuditDenied("origin_invalid") from None
    if (parsed.scheme != "https" or parsed.hostname != HOST
            or port not in (None, 443) or parsed.username is not None
            or parsed.password is not None or parsed.path not in ("", "/")
            or parsed.query or parsed.fragment):
        raise AuditDenied("origin_invalid")
    return API_ROOT


def _get_collection(url: str, token: str, opener) -> Mapping:
    if not isinstance(token, str) or not token or any(ch.isspace() for ch in token):
        raise AuditDenied("authorized_admin_token_required")
    req = request.Request(url, method="GET", headers={
        "Authorization": "Bearer " + token, "Accept": "application/json",
        "Cache-Control": "no-store",
    })
    try:
        with opener.open(req, timeout=12) as response:
            if response.status != 200:
                raise AuditDenied("collection_api_unavailable")
            raw = response.read(MAX_BYTES + 1)
    except (error.HTTPError, error.URLError, TimeoutError, OSError):
        raise AuditDenied("collection_api_unavailable") from None
    if len(raw) > MAX_BYTES:
        raise AuditDenied("collection_response_oversized")
    try:
        result = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise AuditDenied("collection_response_invalid") from None
    if not isinstance(result, dict):
        raise AuditDenied("collection_response_invalid")
    return result


def _compact(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    # Never remove whitespace inside quoted literals: e.g. auth.id != " "
    # must NOT be normalized into the required auth.id != "" check.
    normalized = value.replace("'", '"')
    if re.findall(r'"[^"\\]*"', normalized) != ['""']:
        return None
    return re.sub(r"\s+", "", normalized)


def _rule(*terms: str) -> str:
    return "&&".join(terms)


AUTH = '@request.auth.id!=""'
VERIFIED = '@request.auth.verified=true'
OWNER = 'user_id=@request.auth.id'
BODY_OWNER = '@request.body.user_id=@request.auth.id'


def _unique_index(indexes: object) -> bool:
    if not isinstance(indexes, list):
        return False
    pattern = re.compile(
        r'^CREATE\s+UNIQUE\s+INDEX\s+(?:IF\s+NOT\s+EXISTS\s+)?'
        r'"?[A-Za-z][A-Za-z0-9_]*"?\s+ON\s+"?nija_broker_vault"?\s*'
        r'\(([^()]*)\)\s*;?$', re.IGNORECASE,
    )
    for row in indexes:
        if not isinstance(row, str):
            continue
        match = pattern.fullmatch(row.strip())
        if match is None:
            continue
        names = [part.strip().strip('"').lower() for part in match.group(1).split(',')]
        if len(names) == 3 and set(names) == {"user_id", "broker", "environment"}:
            return True
    return False


def inspect_collection(vault: Mapping, users: Mapping) -> dict:
    """Structural checks only. Superuser rules cannot prove member isolation."""
    failed = []
    if vault.get("name") != "nija_broker_vault" or vault.get("type") != "base":
        failed.append("vault_collection_identity")
    if users.get("name") != "users" or users.get("type") != "auth":
        failed.append("user_collection_identity")
    user_collection_id = users.get("id")
    if not isinstance(user_collection_id, str) or not user_collection_id:
        failed.append("user_collection_id")
    expected = {
        "listRule": _rule(AUTH, VERIFIED, OWNER),
        "viewRule": _rule(AUTH, VERIFIED, OWNER),
        "createRule": _rule(AUTH, VERIFIED, BODY_OWNER),
    }
    for key, rule in expected.items():
        if _compact(vault.get(key)) != rule:
            failed.append("rule_" + key)
    if vault.get("updateRule") is not None and _compact(vault.get("updateRule")) != _rule(AUTH, VERIFIED, OWNER, BODY_OWNER):
        failed.append("rule_updateRule")
    if vault.get("deleteRule") is not None and _compact(vault.get("deleteRule")) != _rule(AUTH, VERIFIED, OWNER):
        failed.append("rule_deleteRule")
    if not _unique_index(vault.get("indexes")):
        failed.append("scope_unique_index")
    fields = vault.get("fields", vault.get("schema"))
    if not isinstance(fields, list):
        failed.append("field_schema_unavailable")
    else:
        named = {f.get("name"): f for f in fields if isinstance(f, dict) and isinstance(f.get("name"), str)}
        for field in ("user_id", "broker", "environment", "ciphertext"):
            if field not in named:
                failed.append("field_" + field)
        relation = named.get("user_id", {})
        rel_opts = relation.get("options", {})
        rel_opts = rel_opts if isinstance(rel_opts, Mapping) else {}
        collection_id = relation.get("collectionId", rel_opts.get("collectionId"))
        max_select = relation.get("maxSelect", rel_opts.get("maxSelect"))
        if (relation.get("type") != "relation"
                or relation.get("required") is not True
                or relation.get("hidden") is True
                or collection_id != user_collection_id
                or type(max_select) is not int or max_select not in (0, 1)):
            failed.append("verified_owner_relation")
        # Reject schema shapes that silently permit unsupported broker scopes
        # or hide owner-scoped metadata from the member API. Legacy and
        # current PocketBase select-field option locations are both supported.
        for name, expected_values in (
            ("broker", {"kraken", "alpaca", "coinbase", "okx"}),
            ("environment", {"paper", "live"}),
        ):
            field = named.get(name, {})
            options = field.get("options", {})
            options = options if isinstance(options, Mapping) else {}
            values = field.get("values", options.get("values"))
            select_max = field.get("maxSelect", options.get("maxSelect"))
            if (field.get("type") != "select"
                    or field.get("required") is not True
                    or field.get("hidden") is True
                    or not isinstance(values, list)
                    or len(values) != len(expected_values)
                    or any(not isinstance(item, str) for item in values)
                    or set(values) != expected_values
                    or type(select_max) is not int or select_max not in (0, 1)):
                failed.append("field_scope_" + name)
        ciphertext = named.get("ciphertext", {})
        if (ciphertext.get("type") != "text"
                or ciphertext.get("required") is not True
                or ciphertext.get("hidden") is True):
            failed.append("field_ciphertext_storage")
    return {
        "status": "STRUCTURE_MATCH" if not failed else "REVIEW_REQUIRED",
        "structural_rule_checks_passed": not failed,
        "missing_or_unverified": sorted(set(failed)),
        "cross_member_negative_tests_passed": False,
        "billing_identity_mapping_certified": False,
        "encryption_key_custody_certified": False,
        "member_vault_certified": False,
        "intake_authorized": False,
        "configuration_changed": False,
        "trading_authorized": False,
    }


def inspect_live(base_url: str, token: str, *, opener=None) -> dict:
    root = _canonical(base_url)
    if not isinstance(token, str) or not token or any(c.isspace() for c in token):
        raise AuditDenied("authorized_admin_token_required")
    op = opener or request.build_opener(_NoRedirect)
    vault = _get_collection(root + "nija_broker_vault", token, op)
    users = _get_collection(root + "users", token, op)
    return inspect_collection(vault, users)


def main() -> int:
    try:
        result = inspect_live(
            os.environ.get("NIJA_POCKETBASE_URL", ""),
            os.environ.get("NIJA_POCKETBASE_ADMIN_TOKEN", ""),
        )
        print(json.dumps(result, sort_keys=True, separators=(",", ":")))
        return 0 if result["structural_rule_checks_passed"] else 2
    except AuditDenied as exc:
        print(json.dumps({
            "status": "REVIEW_REQUIRED", "failure_code": str(exc),
            "member_vault_certified": False, "intake_authorized": False,
            "configuration_changed": False, "trading_authorized": False,
        }, sort_keys=True, separators=(",", ":")))
        return 2


if __name__ == "__main__":
    sys.exit(main())
