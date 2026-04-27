#!/usr/bin/env python3
"""Real-time dashboard API for NIJA.

This service provides a read-only monitoring surface for platform and user telemetry.
It is intentionally decoupled from trading execution logic.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from collections import Counter, defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Deque, Dict, Iterable, List, Optional, Tuple

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse, PlainTextResponse, StreamingResponse
from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, Gauge, generate_latest

logger = logging.getLogger("realtime_dashboard_api")
logging.basicConfig(
    level=os.getenv("DASHBOARD_LOG_LEVEL", "INFO"),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)


@dataclass
class DashboardState:
    last_refresh_utc: Optional[str] = None
    bot_metrics: Dict[str, float] = field(default_factory=dict)
    platform: Dict[str, Any] = field(default_factory=dict)
    users: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    signals: Dict[str, Any] = field(default_factory=dict)
    recency_events: Deque[Dict[str, Any]] = field(default_factory=lambda: deque(maxlen=200))
    errors: List[str] = field(default_factory=list)


class RealtimeDashboardCollector:
    def __init__(
        self,
        bot_metrics_url: str,
        bot_status_url: str,
        data_root: Path,
        refresh_interval_s: int,
    ) -> None:
        self.bot_metrics_url = bot_metrics_url
        self.bot_status_url = bot_status_url
        self.data_root = data_root
        self.refresh_interval_s = refresh_interval_s

        self._state = DashboardState()
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

        # Prometheus registry for this API's own derived metrics.
        self._registry = CollectorRegistry()
        self._g_platform_balance = Gauge(
            "nija_dashboard_platform_balance_usd",
            "Aggregated platform balance estimated from latest user/account events",
            registry=self._registry,
        )
        self._g_platform_active_positions = Gauge(
            "nija_dashboard_platform_active_positions",
            "Aggregated active positions reconstructed from trade events",
            registry=self._registry,
        )
        self._g_users_seen = Gauge(
            "nija_dashboard_users_seen",
            "Number of users currently represented in telemetry",
            registry=self._registry,
        )
        self._g_signals_5m = Gauge(
            "nija_dashboard_signals_last_5m",
            "Estimated signal events in the last five minutes",
            registry=self._registry,
        )

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="RealtimeDashboardCollector")
        self._thread.start()
        logger.info("Realtime dashboard collector started (interval=%ss)", self.refresh_interval_s)

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)

    def snapshot(self) -> DashboardState:
        with self._lock:
            return DashboardState(
                last_refresh_utc=self._state.last_refresh_utc,
                bot_metrics=dict(self._state.bot_metrics),
                platform=dict(self._state.platform),
                users={k: dict(v) for k, v in self._state.users.items()},
                signals=dict(self._state.signals),
                recency_events=deque(self._state.recency_events, maxlen=200),
                errors=list(self._state.errors),
            )

    def metrics_payload(self) -> bytes:
        return generate_latest(self._registry)

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self._refresh_once()
            except Exception as exc:  # defensive; collector must not crash
                logger.exception("collector refresh failed: %s", exc)
                with self._lock:
                    self._state.errors.append(f"refresh_failed:{type(exc).__name__}:{exc}")
                    self._state.errors = self._state.errors[-20:]
            self._stop_event.wait(self.refresh_interval_s)

    def _refresh_once(self) -> None:
        errors: List[str] = []
        bot_metrics: Dict[str, float] = {}
        bot_status: Dict[str, Any] = {}

        metrics_ok, fetched_metrics = self._try_fetch_prometheus(self.bot_metrics_url)
        if metrics_ok:
            bot_metrics = fetched_metrics
        else:
            errors.append("bot_metrics_unavailable")

        status_ok, fetched_status = self._try_fetch_json(self.bot_status_url)
        if status_ok:
            bot_status = fetched_status
        else:
            errors.append("bot_status_unavailable")

        users, signals, events = self._load_user_and_signal_telemetry()
        platform = self._build_platform_summary(users, bot_metrics, bot_status)

        self._g_platform_balance.set(float(platform.get("balance_usd", 0.0)))
        self._g_platform_active_positions.set(float(platform.get("active_positions", 0)))
        self._g_users_seen.set(float(len(users)))
        self._g_signals_5m.set(float(signals.get("signals_last_5m", 0)))

        now_utc = datetime.now(timezone.utc).isoformat()
        with self._lock:
            self._state.last_refresh_utc = now_utc
            self._state.bot_metrics = bot_metrics
            self._state.platform = platform
            self._state.users = users
            self._state.signals = signals
            self._state.recency_events = events
            self._state.errors = errors

    def _try_fetch_prometheus(self, url: str) -> Tuple[bool, Dict[str, float]]:
        try:
            with httpx.Client(timeout=4.0) as client:
                response = client.get(url)
                response.raise_for_status()
            return True, self._parse_prometheus_text(response.text)
        except Exception as exc:
            logger.warning("metrics fetch failed (%s): %s", url, exc)
            return False, {}

    def _try_fetch_json(self, url: str) -> Tuple[bool, Dict[str, Any]]:
        try:
            with httpx.Client(timeout=4.0) as client:
                response = client.get(url)
                response.raise_for_status()
            payload = response.json()
            if isinstance(payload, dict):
                return True, payload
            return False, {}
        except Exception as exc:
            logger.warning("json fetch failed (%s): %s", url, exc)
            return False, {}

    def _parse_prometheus_text(self, text: str) -> Dict[str, float]:
        out: Dict[str, float] = {}
        for line in text.splitlines():
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            if len(parts) < 2:
                continue
            metric_name = parts[0].split("{")[0]
            try:
                out[metric_name] = float(parts[-1])
            except ValueError:
                continue
        return out

    def _load_json_lines(self, path: Path) -> Iterable[Dict[str, Any]]:
        if not path.exists():
            return []
        rows: List[Dict[str, Any]] = []
        try:
            with path.open("r", encoding="utf-8") as handle:
                buffer = ""
                for raw in handle:
                    line = raw.strip()
                    if not line:
                        continue
                    # Support both strict jsonl and pretty-printed multi-line objects.
                    if line.startswith("{") and line.endswith("}") and not buffer:
                        try:
                            rows.append(json.loads(line))
                            continue
                        except json.JSONDecodeError:
                            pass

                    buffer += line
                    if line.endswith("}"):
                        try:
                            rows.append(json.loads(buffer))
                        except json.JSONDecodeError:
                            pass
                        buffer = ""
        except Exception as exc:
            logger.warning("failed to read %s: %s", path, exc)
        return rows

    def _load_user_and_signal_telemetry(
        self,
    ) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, Any], Deque[Dict[str, Any]]]:
        trades_path = self.data_root / "audit_logs" / "trades.jsonl"
        positions_path = self.data_root / "audit_logs" / "positions.jsonl"

        trade_events = list(self._load_json_lines(trades_path))
        position_events = list(self._load_json_lines(positions_path))

        users: Dict[str, Dict[str, Any]] = defaultdict(
            lambda: {
                "balance_usd": 0.0,
                "active_positions": 0,
                "signals_total": 0,
                "last_trade_symbol": None,
                "last_update": None,
            }
        )

        open_positions_by_user: Dict[str, Dict[str, Dict[str, Any]]] = defaultdict(dict)
        signal_counter_by_strategy: Counter[str] = Counter()
        recent_events: Deque[Dict[str, Any]] = deque(maxlen=200)

        for event in trade_events:
            user_id = str(event.get("user_id") or "platform")
            event_type = str(event.get("event_type") or "unknown")
            trade_id = str(event.get("trade_id") or "")
            ts = event.get("timestamp")
            symbol = event.get("symbol")
            strategy = str((event.get("event_data") or {}).get("strategy") or "unknown")

            balance = event.get("account_balance_usd")
            if isinstance(balance, (int, float)):
                users[user_id]["balance_usd"] = float(balance)

            users[user_id]["last_trade_symbol"] = symbol
            users[user_id]["last_update"] = ts

            if event_type == "trade_entry":
                users[user_id]["signals_total"] += 1
                signal_counter_by_strategy[strategy] += 1
                if trade_id:
                    open_positions_by_user[user_id][trade_id] = {
                        "symbol": symbol,
                        "timestamp": ts,
                    }
            elif event_type in {"trade_take_profit", "trade_stop_loss", "trade_exit", "position_closed"}:
                if trade_id and trade_id in open_positions_by_user[user_id]:
                    del open_positions_by_user[user_id][trade_id]

            if event_type in {"trade_entry", "trade_take_profit", "trade_stop_loss", "trade_exit"}:
                recent_events.append(
                    {
                        "timestamp": ts,
                        "user_id": user_id,
                        "event_type": event_type,
                        "symbol": symbol,
                        "strategy": strategy,
                    }
                )

        # Position validation logs are useful signal pressure indicators.
        rejected_count = 0
        for event in position_events:
            if not event.get("validation_result", True):
                rejected_count += 1

        now = datetime.now(timezone.utc)
        recent_5m = 0
        for event in recent_events:
            try:
                event_ts = datetime.fromisoformat(str(event["timestamp"]).replace("Z", "+00:00"))
                if (now - event_ts).total_seconds() <= 300:
                    recent_5m += 1
            except Exception:
                continue

        for user_id, positions in open_positions_by_user.items():
            users[user_id]["active_positions"] = len(positions)

        signals = {
            "signals_total": sum(v["signals_total"] for v in users.values()),
            "signals_last_5m": recent_5m,
            "position_rejections_total": rejected_count,
            "by_strategy": dict(signal_counter_by_strategy),
        }

        return dict(users), signals, recent_events

    def _build_platform_summary(
        self,
        users: Dict[str, Dict[str, Any]],
        bot_metrics: Dict[str, float],
        bot_status: Dict[str, Any],
    ) -> Dict[str, Any]:
        balance_sum = sum(float(u.get("balance_usd", 0.0)) for u in users.values())
        active_positions = sum(int(u.get("active_positions", 0)) for u in users.values())

        platform = {
            "balance_usd": round(balance_sum, 6),
            "active_positions": active_positions,
            "users_tracked": len(users),
            "bot_ready": int(bot_metrics.get("nija_ready", 0.0)) == 1,
            "bot_up": int(bot_metrics.get("nija_up", 0.0)) == 1,
            "exchanges_connected": int(bot_metrics.get("nija_exchanges_connected", 0.0)),
            "exchanges_expected": int(bot_metrics.get("nija_exchanges_expected", 0.0)),
            "trading_enabled": int(bot_metrics.get("nija_trading_enabled", 0.0)) == 1,
            "status_source": "bot_status",
        }

        # If status endpoint provides richer fields, keep them visible.
        if bot_status:
            platform["bot_status"] = bot_status.get("status") or bot_status.get("readiness") or "available"

        return platform


BOT_METRICS_URL = os.getenv("BOT_METRICS_URL", "http://bot:5000/metrics")
BOT_STATUS_URL = os.getenv("BOT_STATUS_URL", "http://bot:5000/status")
DATA_ROOT = Path(os.getenv("DASHBOARD_DATA_ROOT", "/app/data"))
REFRESH_INTERVAL_S = int(os.getenv("DASHBOARD_REFRESH_INTERVAL_SECONDS", "5"))
DASHBOARD_PORT = int(os.getenv("DASHBOARD_PORT", "9000"))

collector = RealtimeDashboardCollector(
    bot_metrics_url=BOT_METRICS_URL,
    bot_status_url=BOT_STATUS_URL,
    data_root=DATA_ROOT,
    refresh_interval_s=REFRESH_INTERVAL_S,
)
collector.start()

app = FastAPI(
    title="NIJA Realtime Dashboard API",
    version="1.0.0",
    description="Realtime platform and per-user telemetry for Grafana/UI",
)


@app.get("/health")
def health() -> Dict[str, Any]:
    state = collector.snapshot()
    return {
        "status": "ok",
        "last_refresh_utc": state.last_refresh_utc,
        "errors": state.errors,
    }


@app.get("/api/v1/overview")
def overview() -> Dict[str, Any]:
    state = collector.snapshot()
    return {
        "platform": state.platform,
        "signals": state.signals,
        "users": state.users,
        "last_refresh_utc": state.last_refresh_utc,
        "errors": state.errors,
    }


@app.get("/api/v1/users")
def users() -> Dict[str, Any]:
    state = collector.snapshot()
    return {
        "count": len(state.users),
        "users": state.users,
        "last_refresh_utc": state.last_refresh_utc,
    }


@app.get("/api/v1/signals")
def signals() -> Dict[str, Any]:
    state = collector.snapshot()
    return {
        "signals": state.signals,
        "recent_events": list(state.recency_events),
        "last_refresh_utc": state.last_refresh_utc,
    }


@app.get("/api/v1/users/{user_id}")
def user_detail(user_id: str) -> Dict[str, Any]:
    state = collector.snapshot()
    if user_id not in state.users:
        raise HTTPException(status_code=404, detail=f"user_id not found: {user_id}")
    return {
        "user_id": user_id,
        "telemetry": state.users[user_id],
        "last_refresh_utc": state.last_refresh_utc,
    }


@app.get("/api/v1/stream")
def stream() -> StreamingResponse:
    def event_stream() -> Iterable[str]:
        while True:
            state = collector.snapshot()
            payload = {
                "platform": state.platform,
                "signals": state.signals,
                "users": state.users,
                "last_refresh_utc": state.last_refresh_utc,
            }
            yield f"data: {json.dumps(payload)}\n\n"
            time.sleep(REFRESH_INTERVAL_S)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.get("/metrics")
def metrics() -> PlainTextResponse:
    return PlainTextResponse(collector.metrics_payload().decode("utf-8"), media_type=CONTENT_TYPE_LATEST)


@app.get("/")
def root() -> JSONResponse:
    return JSONResponse(
        {
            "service": "nija-realtime-dashboard-api",
            "version": "1.0.0",
            "endpoints": [
                "/health",
                "/metrics",
                "/api/v1/overview",
                "/api/v1/users",
                "/api/v1/users/{user_id}",
                "/api/v1/signals",
                "/api/v1/stream",
            ],
        }
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("realtime_dashboard_api:app", host="0.0.0.0", port=DASHBOARD_PORT)
