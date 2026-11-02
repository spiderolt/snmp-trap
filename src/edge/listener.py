from __future__ import annotations

import socket
import threading
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from edge.config import EdgeConfig
from edge.payload import event_payload
from edge.publisher import PublishError, publish_event
from edge.url import ingest_url
from trap_receiver.adapters.registry import default_registry
from trap_receiver.contract import isoformat
from trap_receiver.decoder import TrapDecodeError, decode_snmp_trap
from trap_receiver.security import Allowlist, SlidingWindowRateLimiter, parse_allowlist, parse_csv


def _local_day(now: datetime) -> date:
    try:
        zone = ZoneInfo("America/Sao_Paulo")
    except Exception:
        zone = timezone.utc
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return now.astimezone(zone).date()


class EdgeStats:
    def __init__(self) -> None:
        self.received = 0
        self.sent = 0
        self.last_error = ""
        self.listening_port: int | None = None
        self.counted_on: date | None = None
        self.last_received_at: datetime | None = None
        self._lock = threading.Lock()

    def view(self, now: datetime | None = None) -> tuple[int, int, datetime | None]:
        now = now or datetime.now(timezone.utc)
        with self._lock:
            self._roll_locked(now)
            return self.received, self.sent, self.last_received_at

    def record_received(self, now: datetime | None = None) -> None:
        now = now or datetime.now(timezone.utc)
        with self._lock:
            self.last_received_at = now
            self._roll_locked(now)
            self.received += 1

    def record_sent(self, now: datetime | None = None) -> None:
        now = now or datetime.now(timezone.utc)
        with self._lock:
            self._roll_locked(now)
            self.sent += 1

    def _roll_locked(self, now: datetime) -> None:
        day = _local_day(now)
        if self.counted_on == day:
            return
        self.received = 0
        self.sent = 0
        self.counted_on = day


class TrapListener:
    def __init__(self, *, allowlist: Allowlist, max_payload_bytes: int = 2048) -> None:
        self.allowlist = allowlist
        self.max_payload_bytes = max_payload_bytes
        self.rate_limiter = SlidingWindowRateLimiter(30, 10)
        self.registry = default_registry()
        self.stats = EdgeStats()
        self._socket: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._config_lock = threading.Lock()
        self.config = EdgeConfig()

    def set_config(self, config: EdgeConfig) -> None:
        allowlist = Allowlist(parse_allowlist(config.allowlist))
        with self._config_lock:
            self.config = config
            self.allowlist = allowlist

    def current_config(self) -> EdgeConfig:
        with self._config_lock:
            return EdgeConfig(
                trap_port=self.config.trap_port,
                api_host=self.config.api_host,
                token=self.config.token,
                allowlist=self.config.allowlist,
            )

    def bind(self, port: int) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("0.0.0.0", port))
        except OSError:
            sock.close()
            raise
        sock.settimeout(1.0)
        with self._lock:
            previous = self._socket
            self._socket = sock
            self.stats.listening_port = port
        if previous is not None:
            previous.close()

    def serve_forever(self) -> None:
        while not self._stop.is_set():
            with self._lock:
                sock = self._socket
            if sock is None:
                self._stop.wait(0.2)
                continue
            try:
                payload, address = sock.recvfrom(self.max_payload_bytes + 64)
            except socket.timeout:
                continue
            except OSError:
                if self._stop.is_set():
                    break
                continue
            try:
                self._handle(payload, address[0])
            except Exception:
                self.stats.last_error = "Falha ao processar o trap."

    def start(self) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = threading.Thread(
                target=self.serve_forever,
                name="trap-listener",
                daemon=True,
            )
            self._thread.start()

    def reload_listener(self) -> str:
        port = self.current_config().trap_port
        self.start()
        try:
            self.bind(port)
        except OSError as exc:
            message = f"Não foi possível abrir a porta {port}: {exc}"
            self.stats.last_error = message
            return message
        self.stats.last_error = ""
        return ""

    def stop(self) -> None:
        self._stop.set()
        with self._lock:
            sock = self._socket
            self._socket = None
        if sock is not None:
            sock.close()

    def _handle(self, payload: bytes, source_ip: str) -> None:
        self.stats.record_received()
        if len(payload) > self.max_payload_bytes:
            self.stats.last_error = "Trap maior que o limite."
            return
        if not self.allowlist.allows(source_ip):
            self.stats.last_error = f"Origem {source_ip} fora da allowlist."
            return
        if not self.rate_limiter.allow(source_ip):
            self.stats.last_error = f"Taxa excedida para {source_ip}."
            return
        try:
            decoded = decode_snmp_trap(payload)
        except TrapDecodeError as exc:
            self.stats.last_error = str(exc)
            return

        received_at = isoformat(datetime.now(timezone.utc))
        result = self.registry.decode(
            source_ip=source_ip,
            olt_id=None,
            varbinds=decoded.varbinds,
            received_at=received_at,
            community_present=bool(decoded.community),
        )
        if result.status == "ignore":
            return

        config = self.current_config()
        if config.api_host == "" or config.token == "":
            self.stats.last_error = "Informe o endereço da API e o token."
            return
        try:
            url = ingest_url(config.api_host)
        except ValueError as exc:
            self.stats.last_error = str(exc)
            return

        body = event_payload(
            source_ip=source_ip,
            decoded=result,
            received_at=received_at,
            community_present=bool(decoded.community),
            raw_payload=payload,
        )
        try:
            publish_event(url, config.token, body)
        except PublishError as exc:
            self.stats.last_error = str(exc)
            return
        self.stats.record_sent()
        self.stats.last_error = ""


def allowlist_from_csv(raw: str) -> Allowlist:
    return Allowlist(parse_csv(raw))
