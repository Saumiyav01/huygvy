# backend/telemetry_emitter.py
# backend/telemetry_emitter.py
"""
Resilient TelemetryEmitter.
Drop-in replacement: defines TelemetryEmitter and NullTelemetry.
"""

import socket
import time
import json
import logging
from typing import Optional

logger = logging.getLogger(__name__)

class NullTelemetry:
    """A no-op telemetry replacement used when telemetry is disabled/unavailable."""
    def connect(self):
        logger.info("NullTelemetry: connect() called (no-op)")

    def send(self, payload: dict):
        logger.debug("NullTelemetry: dropping payload (telemetry disabled).")

    def maybe_send_heartbeat(self, meta: dict):
        pass

    def close(self):
        logger.info("NullTelemetry: close() called (no-op)")


class TelemetryEmitter:
    def __init__(self, host: str = "127.0.0.1", port: int = 6000,
                 max_retries: int = 6, base_backoff: float = 0.5,
                 heartbeat_interval: Optional[int] = 10,
                 sock_timeout: float = 2.0):
        self.host = host
        self.port = int(port)
        self.max_retries = max_retries
        self.base_backoff = base_backoff
        self.heartbeat_interval = heartbeat_interval
        self.sock_timeout = sock_timeout

        self.sock: Optional[socket.socket] = None
        self.last_heartbeat_ts = 0.0
        self.connected = False

    def connect(self):
        if self.connected and self.sock:
            return
        backoff = self.base_backoff
        for attempt in range(self.max_retries):
            try:
                logger.info(f"TelemetryEmitter: attempting connect to {self.host}:{self.port} (attempt {attempt+1})")
                s = socket.create_connection((self.host, self.port), timeout=self.sock_timeout)
                s.setblocking(False)
                self.sock = s
                self.connected = True
                logger.info("TelemetryEmitter: connected")
                return
            except Exception as exc:
                logger.warning(f"TelemetryEmitter: connect failed (attempt {attempt+1}): {exc}")
                time.sleep(backoff)
                backoff = min(backoff * 2, 10.0)

        logger.error("TelemetryEmitter: unreachable after retries; telemetry disabled for this run.")
        self.sock = None
        self.connected = False

    def send(self, payload: dict):
        if payload is None:
            return
        if not self.connected or self.sock is None:
            self.connect()
        if not self.connected or self.sock is None:
            logger.debug("TelemetryEmitter: not connected — dropping telemetry payload.")
            return
        try:
            data = json.dumps(payload, default=str).encode("utf-8") + b"\n"
            self.sock.sendall(data)
            logger.debug("TelemetryEmitter: sent payload (len=%d)", len(data))
        except (BlockingIOError, BrokenPipeError, ConnectionResetError, socket.error) as exc:
            logger.warning("TelemetryEmitter: send failed (%s) — closing socket and deferring reconnect", exc)
            try:
                if self.sock:
                    self.sock.close()
            except Exception:
                pass
            self.sock = None
            self.connected = False
        except Exception as exc:
            logger.exception("TelemetryEmitter: unexpected error on send — dropping payload: %s", exc)
            try:
                if self.sock:
                    self.sock.close()
            except Exception:
                pass
            self.sock = None
            self.connected = False

    def maybe_send_heartbeat(self, meta: dict):
        if not self.heartbeat_interval:
            return
        now = time.time()
        if now - self.last_heartbeat_ts < self.heartbeat_interval:
            return
        self.last_heartbeat_ts = now
        heartbeat = {"type": "heartbeat", "ts": now, "meta": meta}
        logger.debug("TelemetryEmitter: sending heartbeat")
        self.send(heartbeat)

    def close(self):
        try:
            if self.sock:
                self.sock.close()
        except Exception:
            pass
        self.sock = None
        self.connected = False
        logger.info("TelemetryEmitter: closed")

