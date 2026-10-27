from __future__ import annotations

from hashlib import sha256
from typing import Any, Optional
from uuid import UUID

from trap_receiver.oids import DISCONNECTION_REASONS, Oid
from trap_receiver.adapters.base import TrapAdapter
from trap_receiver.contract import CanonicalTrapEvent, DecodeResult, payload_hash

_SNMP_TRAP_OID = Oid.SNMP_TRAP_OID.value

_ONU_OFFLINE = {
    Oid.HW_GPON_ONT_LOS_ALARM.value,
    Oid.HW_GPON_ONT_DYING_GASP.value,
    Oid.HW_GPON_ONT_OFFLINE.value,
}
_ONU_ONLINE = {
    Oid.HW_GPON_ONT_LOS_CLEAR.value,
    Oid.HW_GPON_ONT_DYING_GASP_CLEAR.value,
    Oid.HW_GPON_ONT_ONLINE.value,
}
_PON_DOWN = {Oid.HW_XPON_PORT_LOS.value, Oid.LINK_DOWN.value}
_PON_UP = {Oid.HW_XPON_PORT_LOS_CLEAR.value, Oid.LINK_UP.value}

_IDENTITY_BASES = (
    Oid.HW_GPON_ONT_IF_INDEX.value,
    Oid.HW_GPON_ONT_ID.value,
    Oid.ONU_STATS_STATUS.value,
    Oid.ONU_STATS_LAST_DOWN_CAUSE.value,
    Oid.ONU_SERIAL.value,
    Oid.ONU_DESC.value,
    Oid.IF_INDEX.value,
    Oid.IF_NAME.value,
    Oid.IF_DESCR.value,
    Oid.IF_OPER_STATUS.value,
)

_CAUSE_BASES = (
    Oid.ONU_STATS_LAST_DOWN_CAUSE.value,
    Oid.HW_GPON_ONT_ID.value,
)


def normalize_oid(oid: str | None) -> str:
    text = str(oid or "").strip()
    if text.startswith("."):
        text = text[1:]
    if text.endswith(".0") and text != "1.3.6.1.2.1.1.3.0" and text != _SNMP_TRAP_OID:
        # Keep instance suffixes; only strip a lone .0 on notification OIDs later.
        pass
    return text


def strip_notification_suffix(oid: str) -> str:
    if oid.endswith(".0") and oid.count(".") > 6:
        candidate = oid[:-2]
        if candidate in _ONU_OFFLINE | _ONU_ONLINE | _PON_DOWN | _PON_UP:
            return candidate
    return oid


class HuaweiMA5600TrapAdapter(TrapAdapter):
    vendor = "huawei_ma5600"

    def matches(self, trap_oid: str | None, varbinds: list[dict[str, Any]]) -> bool:
        oid = strip_notification_suffix(normalize_oid(trap_oid or _trap_oid_from_varbinds(varbinds)))
        if oid.startswith("1.3.6.1.4.1.2011."):
            return True
        if oid in {Oid.LINK_DOWN.value, Oid.LINK_UP.value}:
            return any(
                normalize_oid(str(item.get("oid") or "")).startswith("1.3.6.1.4.1.2011.")
                for item in varbinds
            ) or _looks_like_pon_ifname(varbinds)
        return False

    def decode(
        self,
        *,
        source_ip: str,
        olt_id: Optional[int],
        varbinds: list[dict[str, Any]],
        received_at: str,
        community_present: bool = False,
    ) -> DecodeResult:
        cleaned = [
            {"oid": normalize_oid(str(item.get("oid") or "")), "value": item.get("value")}
            for item in varbinds
        ]
        trap_oid = strip_notification_suffix(
            normalize_oid(_trap_oid_from_varbinds(cleaned) or "")
        )
        digest = payload_hash(cleaned, source_ip=source_ip, trap_oid=trap_oid)

        if not trap_oid:
            return DecodeResult.quarantine(
                "missing_trap_oid",
                payload_hash=digest,
                raw_varbinds=cleaned,
            )

        event_type = self._event_type(trap_oid)
        if event_type is None:
            return DecodeResult.quarantine(
                "unknown_trap_oid",
                trap_oid=trap_oid,
                payload_hash=digest,
                raw_varbinds=cleaned,
            )

        pon_index, onu_index = self._extract_indexes(cleaned, event_type)
        if event_type.startswith("onu_") and (not pon_index or onu_index is None):
            return DecodeResult.quarantine(
                "unresolved_onu_index",
                trap_oid=trap_oid,
                payload_hash=digest,
                raw_varbinds=cleaned,
            )
        if event_type.startswith("pon_") and not pon_index:
            return DecodeResult.quarantine(
                "unresolved_pon_index",
                trap_oid=trap_oid,
                payload_hash=digest,
                raw_varbinds=cleaned,
            )

        reason = self._extract_reason(trap_oid, cleaned)
        event_id = str(
            UUID(sha256(f"{digest}|{received_at}".encode("utf-8")).hexdigest()[:32])
        )
        event = CanonicalTrapEvent(
            event_id=event_id,
            source="snmp_trap",
            received_at=received_at,
            source_ip=source_ip,
            olt_id=olt_id,
            pon_index=str(pon_index) if pon_index is not None else None,
            onu_index=onu_index,
            event_type=event_type,
            reason=reason,
            vendor=self.vendor,
            trap_oid=trap_oid,
            vendor_payload_hash=digest,
            raw_varbinds=cleaned,
            community_present=community_present,
        )
        return DecodeResult.normalized(event)

    def _event_type(self, trap_oid: str) -> Optional[str]:
        if trap_oid in _ONU_OFFLINE:
            return "onu_offline"
        if trap_oid in _ONU_ONLINE:
            return "onu_online"
        if trap_oid in _PON_DOWN:
            return "pon_down"
        if trap_oid in _PON_UP:
            return "pon_up"
        return None

    def _extract_reason(self, trap_oid: str, varbinds: list[dict[str, Any]]) -> str:
        if trap_oid == Oid.HW_GPON_ONT_DYING_GASP.value:
            return "pwr fail"
        if trap_oid in {
            Oid.HW_GPON_ONT_LOS_ALARM.value,
            Oid.HW_XPON_PORT_LOS.value,
            Oid.LINK_DOWN.value,
        }:
            return "los"
        if trap_oid in _ONU_ONLINE | _PON_UP:
            return "n/a"

        for item in varbinds:
            oid = item["oid"]
            if oid == Oid.ONU_STATS_LAST_DOWN_CAUSE.value or oid.startswith(
                f"{Oid.ONU_STATS_LAST_DOWN_CAUSE.value}."
            ):
                mapped = DISCONNECTION_REASONS.get(str(item.get("value")))
                if mapped:
                    return mapped
        return "n/a"

    def _extract_indexes(
        self,
        varbinds: list[dict[str, Any]],
        event_type: str,
    ) -> tuple[Optional[str], Optional[int]]:
        pon_index: Optional[str] = None
        onu_index: Optional[int] = None

        for item in varbinds:
            oid = item["oid"]
            value = item.get("value")
            if oid == Oid.HW_GPON_ONT_IF_INDEX.value or oid.startswith(f"{Oid.IF_INDEX.value}."):
                if value not in (None, ""):
                    pon_index = str(value)
            if oid == Oid.HW_GPON_ONT_ID.value or oid.startswith(f"{Oid.HW_GPON_ONT_ID.value}."):
                parsed = _as_int(value)
                if parsed is not None:
                    onu_index = parsed

            table_index = _table_instance(oid)
            if table_index:
                if table_index[0] and not pon_index:
                    pon_index = table_index[0]
                if table_index[1] is not None and onu_index is None:
                    onu_index = table_index[1]

        if event_type.startswith("pon_") and not pon_index:
            pon_index = _ifindex_value(varbinds)

        return pon_index, onu_index


def _trap_oid_from_varbinds(varbinds: list[dict[str, Any]]) -> Optional[str]:
    for item in varbinds:
        if normalize_oid(str(item.get("oid") or "")) == _SNMP_TRAP_OID:
            return normalize_oid(str(item.get("value") or ""))
    return None


def _as_int(value: Any) -> Optional[int]:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _table_instance(oid: str) -> Optional[tuple[Optional[str], Optional[int]]]:
    for base in _IDENTITY_BASES + _CAUSE_BASES:
        prefix = f"{base}."
        if oid.startswith(prefix):
            suffix = oid[len(prefix):]
            parts = [part for part in suffix.split(".") if part != ""]
            if len(parts) >= 2:
                return parts[0], _as_int(parts[-1])
            if len(parts) == 1:
                return parts[0], None
    return None


def _ifindex_value(varbinds: list[dict[str, Any]]) -> Optional[str]:
    for item in varbinds:
        oid = item["oid"]
        if oid == Oid.IF_INDEX.value or oid.startswith(f"{Oid.IF_INDEX.value}."):
            if item.get("value") not in (None, ""):
                return str(item.get("value"))
        if oid == Oid.HW_GPON_ONT_IF_INDEX.value:
            if item.get("value") not in (None, ""):
                return str(item.get("value"))
    return None


def _looks_like_pon_ifname(varbinds: list[dict[str, Any]]) -> bool:
    tokens = ("gpon", "xpon", "epon", "pon")
    for item in varbinds:
        oid = normalize_oid(str(item.get("oid") or ""))
        if oid.startswith(Oid.IF_NAME.value) or oid.startswith(Oid.IF_DESCR.value):
            label = str(item.get("value") or "").lower()
            if any(token in label for token in tokens):
                return True
    return False
