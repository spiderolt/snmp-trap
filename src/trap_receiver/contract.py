from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
from typing import Any, Literal, Optional

EVENT_TYPES = ("onu_offline", "onu_online", "pon_down", "pon_up")
REASONS = ("los", "pwr fail", "reset", "n/a")
SOURCES = ("snmp_trap", "syslog")

EventType = Literal["onu_offline", "onu_online", "pon_down", "pon_up"]
Reason = Literal["los", "pwr fail", "reset", "n/a"]
DecodeStatus = Literal["normalized", "quarantine", "ignore"]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def isoformat(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def received_bucket(received_at: datetime, seconds: int = 60) -> str:
    epoch = int(received_at.timestamp())
    return str(epoch - (epoch % max(1, seconds)))


def payload_hash(varbinds: list[dict[str, Any]], *, source_ip: str, trap_oid: str | None) -> str:
    digest = sha256()
    digest.update(source_ip.encode("utf-8"))
    digest.update(b"|")
    digest.update((trap_oid or "").encode("utf-8"))
    digest.update(b"|")
    for bind in varbinds:
        oid = str(bind.get("oid") or "")
        value = str(bind.get("value") if bind.get("value") is not None else "")
        digest.update(oid.encode("utf-8"))
        digest.update(b"=")
        digest.update(value.encode("utf-8"))
        digest.update(b";")
    return digest.hexdigest()


@dataclass(slots=True)
class CanonicalTrapEvent:
    event_id: str
    source: str
    received_at: str
    source_ip: str
    olt_id: Optional[int]
    pon_index: Optional[str]
    onu_index: Optional[int]
    event_type: EventType
    reason: Reason
    vendor: str
    trap_oid: str
    vendor_payload_hash: str
    raw_varbinds: list[dict[str, Any]] = field(default_factory=list)
    community_present: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class PersistOutcome:
    event_id: str
    created: bool
    status: str
    published: bool


@dataclass(slots=True)
class DecodeResult:
    status: DecodeStatus
    event: Optional[CanonicalTrapEvent] = None
    quarantine_reason: Optional[str] = None
    trap_oid: Optional[str] = None
    payload_hash: Optional[str] = None
    raw_varbinds: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def normalized(cls, event: CanonicalTrapEvent) -> "DecodeResult":
        return cls(
            status="normalized",
            event=event,
            trap_oid=event.trap_oid,
            payload_hash=event.vendor_payload_hash,
            raw_varbinds=event.raw_varbinds,
        )

    @classmethod
    def quarantine(
        cls,
        reason: str,
        *,
        trap_oid: str | None = None,
        payload_hash: str | None = None,
        raw_varbinds: list[dict[str, Any]] | None = None,
    ) -> "DecodeResult":
        return cls(
            status="quarantine",
            quarantine_reason=reason,
            trap_oid=trap_oid,
            payload_hash=payload_hash,
            raw_varbinds=raw_varbinds or [],
        )

    @classmethod
    def ignore(cls, *, trap_oid: str | None = None) -> "DecodeResult":
        return cls(status="ignore", trap_oid=trap_oid)
