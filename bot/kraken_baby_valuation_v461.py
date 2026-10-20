"""Kraken metadata-only BABY price resolver; no guessed asset aliases."""
import math
from collections.abc import Mapping


def _positive(value):
    try:
        number = float(value)
        return number if math.isfinite(number) and number > 0 else None
    except (TypeError, ValueError, OverflowError):
        return None


def _public(api, endpoint, params=None):
    if api is None or not callable(getattr(api, "query_public", None)):
        return None
    response = api.query_public(endpoint, params or {})
    if not isinstance(response, Mapping) or response.get("error"):
        return None
    result = response.get("result")
    return result if isinstance(result, Mapping) else None


def resolve_baby_usd_price(api):
    """Return USD price only for Kraken-confirmed BABY base and USD quote.

    Unsupported pairs, ambiguous identifiers and missing prices return None.
    Authenticated TradeBalance equity fallback remains owned by broker_manager.
    """
    assets = _public(api, "Assets")
    pairs = _public(api, "AssetPairs")
    if assets is None or pairs is None:
        return None
    baby_codes = {code for code, meta in assets.items()
                  if isinstance(meta, Mapping)
                  and (str(code).upper() == "BABY" or str(meta.get("altname", "")).upper() == "BABY")}
    usd_codes = {code for code, meta in assets.items()
                 if isinstance(meta, Mapping)
                 and (str(code).upper() in {"USD", "ZUSD"} or str(meta.get("altname", "")).upper() == "USD")}
    if len(baby_codes) != 1 or not usd_codes:
        return None
    matching = [(code, meta) for code, meta in pairs.items()
                if isinstance(meta, Mapping) and meta.get("base") in baby_codes
                and meta.get("quote") in usd_codes
                and str(meta.get("status", "online")).lower() == "online"]
    if len(matching) != 1:
        return None
    pair_code = matching[0][0]
    ticker = _public(api, "Ticker", {"pair": pair_code})
    if ticker is None:
        return None
    entry = ticker.get(pair_code)
    if not isinstance(entry, Mapping) and len(ticker) == 1:
        entry = next(iter(ticker.values()))
    if not isinstance(entry, Mapping):
        return None
    last = entry.get("c")
    return _positive(last[0] if isinstance(last, (list, tuple)) and last else None)
