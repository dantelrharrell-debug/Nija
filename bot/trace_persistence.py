"""Persistent trace streaming + Postgres writer for Execution Intelligence Layer v2."""

from __future__ import annotations

import json
import logging
import os
import queue
import threading
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger("nija.trace_persistence")

_EVENTS_STREAM_KEY = "nija:trace:events"
_TERMINAL_STREAM_KEY = "nija:trace:terminal"
_CONSUMER_GROUP = "eil_v2_consumer"
_DEFAULT_BATCH_SIZE = 100
_DEFAULT_FLUSH_INTERVAL_SEC = 10.0


class EILTraceStreamPublisher:
    """Publishes execution trace events to Redis streams (best effort)."""

    def __init__(self) -> None:
        self._enabled = str(os.getenv("NIJA_EIL_ENABLED", "false")).lower() in ("1", "true", "yes")
        self._redis_client = None
        self._connect_attempted = False

    def _client(self):
        if not self._enabled:
            return None
        if self._connect_attempted and self._redis_client is None:
            return None
        if self._redis_client is None:
            self._connect_attempted = True
            try:
                try:
                    from bot.redis_runtime import create_redis
                except ImportError:
                    from redis_runtime import create_redis  # type: ignore[import]
                self._redis_client = create_redis(decode_responses=True)
            except Exception:
                self._redis_client = None
                logger.debug("EIL trace publisher Redis unavailable", exc_info=True)
        return self._redis_client

    @staticmethod
    def _normalize_payload(payload: Dict[str, Any]) -> Dict[str, str]:
        out: Dict[str, str] = {}
        for key, value in payload.items():
            if value is None:
                continue
            if isinstance(value, (dict, list, tuple)):
                out[str(key)] = json.dumps(value, default=str)
            else:
                out[str(key)] = str(value)
        return out

    def publish_event(self, payload: Dict[str, Any]) -> None:
        """Publish trace stage event to hot events stream."""
        client = self._client()
        if client is None:
            return
        try:
            client.xadd(
                _EVENTS_STREAM_KEY,
                fields=self._normalize_payload(payload),
                maxlen=50000,
                approximate=True,
            )
        except Exception:
            logger.debug("EIL trace event publish failed", exc_info=True)

    def publish_terminal(self, payload: Dict[str, Any]) -> None:
        """Publish terminal trace summary to terminal stream."""
        client = self._client()
        if client is None:
            return
        try:
            client.xadd(
                _TERMINAL_STREAM_KEY,
                fields=self._normalize_payload(payload),
                maxlen=50000,
                approximate=True,
            )
        except Exception:
            logger.debug("EIL terminal event publish failed", exc_info=True)


class EILTracePersistenceWriter:
    """Consumes terminal stream and persists traces to Postgres in batches."""

    def __init__(self) -> None:
        self._enabled = str(os.getenv("NIJA_EIL_ENABLED", "false")).lower() in ("1", "true", "yes")
        self._postgres_url = (os.getenv("NIJA_EIL_POSTGRES_URL", "") or "").strip()
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._queue: "queue.Queue[Dict[str, Any]]" = queue.Queue(maxsize=1000)
        self._batch_size = int(os.getenv("NIJA_EIL_PERSIST_BATCH_SIZE", str(_DEFAULT_BATCH_SIZE)) or _DEFAULT_BATCH_SIZE)
        self._flush_interval = float(
            os.getenv("NIJA_EIL_PERSIST_FLUSH_INTERVAL_S", str(_DEFAULT_FLUSH_INTERVAL_SEC)) or _DEFAULT_FLUSH_INTERVAL_SEC
        )
        self._redis_client = None

    def _redis(self):
        if self._redis_client is not None:
            return self._redis_client
        try:
            try:
                from bot.redis_runtime import create_redis
            except ImportError:
                from redis_runtime import create_redis  # type: ignore[import]
            self._redis_client = create_redis(decode_responses=True)
            try:
                self._redis_client.xgroup_create(_TERMINAL_STREAM_KEY, _CONSUMER_GROUP, id="0", mkstream=True)
            except Exception:
                pass
            return self._redis_client
        except Exception:
            logger.debug("EIL persistence Redis unavailable", exc_info=True)
            return None

    def start(self) -> None:
        """Start background consumer/persistence thread."""
        if not self._enabled or self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True, name="eil-trace-persistence")
        self._thread.start()

    def stop(self) -> None:
        """Stop background worker."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)

    def _loop(self) -> None:
        last_flush = time.time()
        batch: List[Dict[str, Any]] = []
        while self._running:
            self._poll_stream_once()
            try:
                item = self._queue.get(timeout=0.5)
                batch.append(item)
            except queue.Empty:
                pass

            now = time.time()
            if batch and (len(batch) >= self._batch_size or (now - last_flush) >= self._flush_interval):
                self._flush_batch(batch)
                batch = []
                last_flush = now

    def _poll_stream_once(self) -> None:
        client = self._redis()
        if client is None:
            return
        try:
            rows = client.xreadgroup(
                groupname=_CONSUMER_GROUP,
                consumername=f"eil-writer-{os.getpid()}",
                streams={_TERMINAL_STREAM_KEY: ">"},
                count=50,
                block=50,
            )
            for _, entries in rows:
                for msg_id, fields in entries:
                    payload = self._decode_stream_fields(fields)
                    payload["_redis_msg_id"] = msg_id
                    try:
                        self._queue.put_nowait(payload)
                    except queue.Full:
                        logger.warning("EIL persistence queue full; dropping oldest message")
                        try:
                            self._queue.get_nowait()
                            self._queue.put_nowait(payload)
                        except Exception:
                            pass
                    try:
                        client.xack(_TERMINAL_STREAM_KEY, _CONSUMER_GROUP, msg_id)
                    except Exception:
                        pass
        except Exception:
            logger.debug("EIL persistence stream poll failed", exc_info=True)

    @staticmethod
    def _decode_stream_fields(fields: Dict[str, Any]) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        for key, value in (fields or {}).items():
            k = str(key)
            v = value
            if isinstance(v, str):
                vv = v.strip()
                if vv.startswith("{") or vv.startswith("["):
                    try:
                        out[k] = json.loads(vv)
                        continue
                    except Exception:
                        pass
            out[k] = v
        return out

    @staticmethod
    def _safe_float(value: Any, default: float = 0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def _flush_batch(self, batch: List[Dict[str, Any]]) -> None:
        if not batch:
            return
        if not self._postgres_url:
            # Graceful degradation: remain stream-backed only.
            return

        try:
            import psycopg2
        except Exception:
            return

        try:
            with psycopg2.connect(self._postgres_url) as conn:
                with conn.cursor() as cur:
                    for row in batch:
                        trace_id = str(row.get("trace_id") or "")
                        if not trace_id:
                            continue
                        trace_path = row.get("trace_path")
                        if isinstance(trace_path, str):
                            try:
                                trace_path = json.loads(trace_path)
                            except Exception:
                                trace_path = [trace_path]
                        if not isinstance(trace_path, list):
                            trace_path = []

                        cur.execute(
                            """
                            INSERT INTO execution_traces (
                                trace_id, pair, side, status, terminal_reason,
                                regime, confidence, adx, gate_score, ecel_decision,
                                slippage_bps, fill_latency_ms, quality_grade,
                                trace_path, created_at, filled_at
                            ) VALUES (
                                %s, %s, %s, %s, %s,
                                %s, %s, %s, %s, %s,
                                %s, %s, %s,
                                %s, to_timestamp(%s), to_timestamp(%s)
                            ) ON CONFLICT (trace_id) DO NOTHING
                            """,
                            (
                                trace_id,
                                row.get("pair"),
                                row.get("side"),
                                row.get("status"),
                                row.get("terminal_reason"),
                                row.get("regime"),
                                self._safe_float(row.get("confidence"), 0.0),
                                self._safe_float(row.get("adx"), 0.0),
                                self._safe_float(row.get("gate_score"), 0.0),
                                row.get("ecel_decision"),
                                self._safe_float(row.get("slippage_bps"), 0.0),
                                self._safe_float(row.get("fill_latency_ms"), 0.0),
                                row.get("quality_grade") or "",
                                trace_path,
                                self._safe_float(row.get("created_at"), time.time()),
                                self._safe_float(row.get("filled_at"), row.get("updated_at") or time.time()),
                            ),
                        )

                        events = row.get("events") or []
                        if isinstance(events, str):
                            try:
                                events = json.loads(events)
                            except Exception:
                                events = []
                        for event in events:
                            event = event or {}
                            cur.execute(
                                """
                                INSERT INTO trace_stage_events (
                                    trace_id, stage, outcome, reason, extra, ts
                                ) VALUES (
                                    %s, %s, %s, %s, %s, to_timestamp(%s)
                                ) ON CONFLICT DO NOTHING
                                """,
                                (
                                    trace_id,
                                    event.get("stage"),
                                    event.get("outcome"),
                                    event.get("reason"),
                                    json.dumps(event.get("extra") or {}),
                                    self._safe_float(event.get("timestamp"), time.time()),
                                ),
                            )
                conn.commit()
        except Exception:
            logger.debug("EIL persistence batch flush failed", exc_info=True)


_publisher_singleton: Optional[EILTraceStreamPublisher] = None
_persistence_singleton: Optional[EILTracePersistenceWriter] = None
_singleton_lock = threading.Lock()


def get_eil_trace_publisher() -> EILTraceStreamPublisher:
    """Return singleton trace stream publisher."""
    global _publisher_singleton
    if _publisher_singleton is None:
        with _singleton_lock:
            if _publisher_singleton is None:
                _publisher_singleton = EILTraceStreamPublisher()
    return _publisher_singleton


def get_eil_trace_persistence_writer() -> EILTracePersistenceWriter:
    """Return singleton persistence writer and ensure background start."""
    global _persistence_singleton
    if _persistence_singleton is None:
        with _singleton_lock:
            if _persistence_singleton is None:
                _persistence_singleton = EILTracePersistenceWriter()
                _persistence_singleton.start()
    return _persistence_singleton
