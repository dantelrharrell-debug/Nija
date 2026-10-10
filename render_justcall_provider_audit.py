"""Read-only JustCall provider-history reconciliation for NIJA's daily call audit.

No calls are placed, contacts exposed, or compliance gates modified.
A count is authoritative only if every provider history page from both
JustCall and Sales Dialer was fetched and parsed successfully.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from render_outreach_routes import (
    OutreachConfigurationError,
    OutreachProviderError,
    _provider_request,
)

_PACIFIC = ZoneInfo("America/Los_Angeles")
_PAGE_SIZE = 100
_MAX_PAGES = 30  # fail closed on unusual volume; never report a partial count as verified
_EXCLUDED_CALL_TYPES = ("blocked", "restricted", "cancelled", "abandoned before ringing")


class ProviderHistoryIncomplete(RuntimeError):
    """Provider history cannot support a defensible count."""


def _records(response: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if response.get("success") is False or str(response.get("status", "")).lower() in {
        "error", "failed", "failure"
    }:
        raise ProviderHistoryIncomplete("provider_reported_failure")
    container: dict[str, Any] = response
    value: object = response.get("data")
    if isinstance(value, dict):
        container = value
        value = next(
            (value[name] for name in ("data", "calls", "records", "items")
             if isinstance(value.get(name), list)),
            None,
        )
    elif not isinstance(value, list):
        value = next(
            (response[name] for name in ("calls", "records", "items")
             if isinstance(response.get(name), list)),
            None,
        )
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise ProviderHistoryIncomplete("provider_response_shape_unverified")
    return value, container


def _call_time_utc(call: dict[str, Any]) -> datetime:
    day = str(call.get("call_date") or "").strip()
    clock = str(call.get("call_time") or "").strip()
    if not day or (len(day) == 10 and not clock):
        raise ProviderHistoryIncomplete("call_utc_timestamp_missing")
    try:
        if len(day) == 10 and clock:
            parsed = datetime.fromisoformat(f"{day}T{clock.replace('Z', '+00:00')}")
        else:
            parsed = datetime.fromisoformat(day.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ProviderHistoryIncomplete("call_utc_timestamp_invalid") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)  # provider documents UTC fields
    return parsed.astimezone(timezone.utc)


def _call_identity(call: dict[str, Any], source: str) -> str:
    sid = str(call.get("call_sid") or "").strip()
    if sid:
        return f"sid:{sid}"
    value = str(call.get("id") or call.get("call_id") or "").strip()
    if value:
        return f"{source}:{value}"
    raise ProviderHistoryIncomplete("provider_call_id_missing")


def _countable(call: dict[str, Any], source: str) -> bool:
    info = call.get("call_info")
    if not isinstance(info, dict):
        raise ProviderHistoryIncomplete("call_info_missing")
    direction = str(info.get("direction") or "").strip().lower()
    if direction and direction != "outgoing":
        return False
    if not direction and source == "justcall":
        raise ProviderHistoryIncomplete("call_direction_unverified")
    call_type = str(info.get("type") or "").strip().lower()
    if any(term in call_type for term in _EXCLUDED_CALL_TYPES):
        return False
    return True


def _history_for_source(
    source: str, path: str, target_date: date
) -> tuple[set[str], dict[str, int]]:
    # JustCall filters by the account user's timezone, which need not be Pacific.
    # Request a deliberately wider interval and classify each call using its
    # provider-documented UTC date/time converted into America/Los_Angeles.
    from_date = target_date - timedelta(days=2)
    to_date = target_date + timedelta(days=2)
    ids: set[str] = set()
    seen_page_signatures: set[tuple[str, ...]] = set()
    scanned = 0
    excluded = 0

    for page in range(_MAX_PAGES):
        query = {
            "from_datetime": f"{from_date.isoformat()} 00:00:00",
            "to_datetime": f"{to_date.isoformat()} 23:59:59",
            "page": page,
            "per_page": _PAGE_SIZE,
            "sort": "id",
            "order": "desc",
        }
        if source == "justcall":
            query["call_direction"] = "Outgoing"
        payload = _provider_request("GET", f"{path}?{urlencode(query)}")
        calls, container = _records(payload)
        scanned += len(calls)
        signature = tuple(_call_identity(call, source) for call in calls)
        if calls and signature in seen_page_signatures:
            raise ProviderHistoryIncomplete("provider_pagination_repeated")
        seen_page_signatures.add(signature)

        for call, key in zip(calls, signature):
            if _call_time_utc(call).astimezone(_PACIFIC).date() != target_date:
                continue
            if _countable(call, source):
                ids.add(key)
            else:
                excluded += 1

        next_link = str(
            container.get("next_page_link") or container.get("nextPageLink")
            or payload.get("next_page_link") or payload.get("nextPageLink") or ""
        ).strip()
        total = container.get("total_count", container.get("totalCount"))
        if total is None:
            total = payload.get("total_count", payload.get("totalCount"))
        more_by_total = (
            isinstance(total, int) and not isinstance(total, bool) and scanned < total
        )
        if not next_link and not more_by_total and len(calls) < _PAGE_SIZE:
            return ids, {"pages": page + 1, "records_scanned": scanned, "excluded": excluded}
    raise ProviderHistoryIncomplete("provider_pagination_limit_reached")


def audit_provider_today(now_utc: datetime | None = None) -> dict[str, Any]:
    now_utc = now_utc or datetime.now(timezone.utc)
    if now_utc.tzinfo is None:
        raise ValueError("now_utc must include timezone")
    target_date = now_utc.astimezone(_PACIFIC).date()
    result: dict[str, Any] = {
        "date": target_date.isoformat(),
        "timezone": "America/Los_Angeles",
        "target": 300,
        "source": "justcall_v2_1_provider_history",
        "verified": False,
        "confirmed_outbound_attempts": None,
        "gap_to_target": None,
        "sources": {},
    }
    verified_ids: set[str] = set()
    for name, path in (
        ("justcall", "/calls"),
        ("sales_dialer", "/sales_dialer/calls"),
    ):
        try:
            ids, info = _history_for_source(name, path, target_date)
        except (ProviderHistoryIncomplete, OutreachConfigurationError, OutreachProviderError) as exc:
            result["state"] = "provider_history_unverified"
            result["blocked_source"] = name
            result["reason"] = (
                str(exc) if isinstance(exc, ProviderHistoryIncomplete)
                else "provider_credentials_missing" if isinstance(exc, OutreachConfigurationError)
                else f"provider_api_error_http_{exc.status_code or 'unknown'}"
            )
            return result
        verified_ids.update(ids)
        result["sources"][name] = {
            "matched_outbound_ids": len(ids),
            **info,
        }
    result.update(
        {
            "state": "verified",
            "verified": True,
            "confirmed_outbound_attempts": len(verified_ids),
            "gap_to_target": max(0, 300 - len(verified_ids)),
        }
    )
    return result
