from __future__ import annotations

import json
import logging
import time
import urllib.parse
import urllib.request
from typing import Any

logger = logging.getLogger("nija.pykrakenapi_ohlc_direct_rest_patch")
_MARKER = "PYKRAKENAPI_OHLC_DIRECT_REST_PATCHED marker=20260708a"
_PATCHED_ATTR = "_nija_pykrakenapi_ohlc_direct_rest_20260708a"


def _int(value: Any, default: int) -> int:
    try:
        return int(float(value or default))
    except Exception:
        return default


def _pair_text(value: Any) -> str:
    return str(value or "").strip().upper().replace("/", "").replace("-", "")


def _request_public_ohlc(pair: str, interval: int, timeout_s: float) -> tuple[list[list[Any]], Any]:
    params = {"pair": pair, "interval": interval}
    url = "https://api.kraken.com/0/public/OHLC?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "NIJA-AI-Trading/pykrakenapi-ohlc-direct-rest-20260708a"},
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:  # nosec: public market-data endpoint
        payload = json.loads(resp.read().decode("utf-8"))
    errors = payload.get("error") or []
    if errors:
        raise RuntimeError("Kraken public OHLC error: " + ", ".join(map(str, errors)))
    result = payload.get("result") or {}
    pair_key = next((key for key in result if key != "last"), None)
    rows = result.get(pair_key) if pair_key else []
    return rows if isinstance(rows, list) else [], result.get("last")


def _rows_to_frame(rows: list[list[Any]], ascending: bool):
    import pandas as pd  # type: ignore

    data = []
    index = []
    for row in rows:
        try:
            ts = int(float(row[0]))
            index.append(pd.to_datetime(ts, unit="s", utc=True))
            data.append(
                {
                    "time": ts,
                    "open": float(row[1]),
                    "high": float(row[2]),
                    "low": float(row[3]),
                    "close": float(row[4]),
                    "vwap": float(row[5]),
                    "volume": float(row[6]),
                    "count": int(float(row[7])) if len(row) > 7 else 0,
                }
            )
        except Exception:
            continue
    frame = pd.DataFrame(data, index=index)
    if not ascending and not frame.empty:
        frame = frame.iloc[::-1]
    return frame


def install_import_hook() -> None:
    try:
        from pykrakenapi import KrakenAPI  # type: ignore
    except Exception as exc:
        logger.warning("PYKRAKENAPI_OHLC_DIRECT_REST_INSTALL_DEFERRED marker=20260708a err=%s", exc)
        return

    original = getattr(KrakenAPI, "get_ohlc_data", None)
    if not callable(original):
        logger.warning("PYKRAKENAPI_OHLC_DIRECT_REST_NO_TARGET marker=20260708a")
        return
    if getattr(original, _PATCHED_ATTR, False):
        return

    def get_ohlc_data_direct(self: Any, pair: Any, interval: int = 1, ascending: bool = False, since: Any = None, *args: Any, **kwargs: Any):
        pair_s = _pair_text(pair)
        interval_i = _int(interval, 1)
        timeout_s = float(kwargs.pop("timeout", 6.0) or 6.0)
        started = time.time()
        try:
            rows, last = _request_public_ohlc(pair_s, interval_i, timeout_s)
            frame = _rows_to_frame(rows, bool(ascending))
            logger.info(
                "PYKRAKENAPI_OHLC_DIRECT_REST_OK marker=20260708a pair=%s interval=%s rows=%d latency_ms=%.1f",
                pair_s,
                interval_i,
                len(frame),
                (time.time() - started) * 1000.0,
            )
            return frame, last
        except Exception as exc:
            logger.warning(
                "PYKRAKENAPI_OHLC_DIRECT_REST_FAILED marker=20260708a pair=%s interval=%s err=%s",
                pair_s,
                interval_i,
                exc,
            )
            import pandas as pd  # type: ignore
            return pd.DataFrame(columns=["time", "open", "high", "low", "close", "vwap", "volume", "count"]), None

    setattr(get_ohlc_data_direct, _PATCHED_ATTR, True)
    setattr(KrakenAPI, "get_ohlc_data", get_ohlc_data_direct)
    logger.warning(_MARKER)
    print("[NIJA-PRINT] PYKRAKENAPI_OHLC_DIRECT_REST_PATCHED marker=20260708a", flush=True)


def install() -> None:
    install_import_hook()
