from __future__ import annotations

from hashlib import sha256
from uuid import UUID

from trap_receiver.contract import DecodeResult


def event_payload(
    *,
    source_ip: str,
    decoded: DecodeResult,
    received_at: str,
    community_present: bool,
    raw_payload: bytes,
) -> dict[str, object]:
    event = decoded.event
    digest = (
        (event.vendor_payload_hash if event else decoded.payload_hash)
        or sha256(raw_payload or source_ip.encode("utf-8")).hexdigest()
    )
    event_id = event.event_id if event else _fallback_event_id(source_ip, decoded, received_at)
    status = "received" if decoded.status == "normalized" and event is not None else "quarantined"
    varbinds = event.raw_varbinds if event else decoded.raw_varbinds
    return {
        "event_id": event_id,
        "source": "snmp_trap",
        "received_at": received_at,
        "source_ip": source_ip,
        "pon_index": event.pon_index if event else None,
        "onu_index": event.onu_index if event else None,
        "event_type": event.event_type if event else None,
        "reason": event.reason if event else None,
        "vendor": event.vendor if event else None,
        "trap_oid": decoded.trap_oid or (event.trap_oid if event else None),
        "vendor_payload_hash": digest,
        "status": status,
        "quarantine_reason": decoded.quarantine_reason,
        "community_present": community_present,
        "raw_payload": {
            "varbinds": varbinds,
            "raw_hex": raw_payload.hex() if raw_payload else None,
        },
    }


def _fallback_event_id(source_ip: str, decoded: DecodeResult, received_at: str) -> str:
    material = f"{source_ip}|{decoded.trap_oid}|{decoded.payload_hash}|{received_at}"
    digest = sha256(material.encode("utf-8")).hexdigest()
    return str(UUID(digest[:32]))
