from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class TrapDecodeError(ValueError):
    """Raised when a UDP datagram is not a usable SNMPv1/v2c trap."""


@dataclass(slots=True)
class DecodedTrap:
    version: int
    community: str
    pdu_type: str
    varbinds: list[dict[str, Any]]


class _BerReader:
    def __init__(self, data: bytes):
        self.data = data
        self.pos = 0

    def remaining(self) -> int:
        return len(self.data) - self.pos

    def read_tlv(self) -> tuple[int, bytes]:
        if self.remaining() < 2:
            raise TrapDecodeError("truncated TLV")
        tag = self.data[self.pos]
        self.pos += 1
        length = self._read_length()
        if self.remaining() < length:
            raise TrapDecodeError("truncated value")
        value = self.data[self.pos : self.pos + length]
        self.pos += length
        return tag, value

    def _read_length(self) -> int:
        if self.remaining() < 1:
            raise TrapDecodeError("truncated length")
        first = self.data[self.pos]
        self.pos += 1
        if first < 0x80:
            return first
        count = first & 0x7F
        if count == 0 or count > 4 or self.remaining() < count:
            raise TrapDecodeError("invalid length")
        length = int.from_bytes(self.data[self.pos : self.pos + count], "big")
        self.pos += count
        return length


def decode_snmp_trap(payload: bytes) -> DecodedTrap:
    if not payload:
        raise TrapDecodeError("empty payload")
    reader = _BerReader(payload)
    tag, body = reader.read_tlv()
    if tag != 0x30:
        raise TrapDecodeError("message is not a SEQUENCE")
    message = _BerReader(body)
    version = _read_integer(message)
    community = _read_octet(message)
    pdu_tag, pdu_body = message.read_tlv()
    pdu = _BerReader(pdu_body)

    if pdu_tag == 0xA7:
        _read_integer(pdu)  # request-id
        _read_integer(pdu)  # error-status
        _read_integer(pdu)  # error-index
        varbinds = _read_varbinds(pdu)
        return DecodedTrap(version=version, community=community, pdu_type="v2_trap", varbinds=varbinds)

    if pdu_tag == 0xA4:
        enterprise = _oid_to_string(_read_raw_oid(pdu))
        agent = _format_ip(_read_ip(pdu))
        generic = _read_integer(pdu)
        specific = _read_integer(pdu)
        _read_timeticks(pdu)
        varbinds = _read_varbinds(pdu)
        trap_oid = _v1_trap_oid(enterprise, generic, specific)
        varbinds.insert(0, {"oid": "1.3.6.1.6.3.1.1.4.1.0", "value": trap_oid})
        varbinds.insert(1, {"oid": "1.3.6.1.6.3.18.1.3.0", "value": agent})
        return DecodedTrap(version=version, community=community, pdu_type="v1_trap", varbinds=varbinds)

    raise TrapDecodeError(f"unsupported PDU tag {pdu_tag:#x}")


def _read_varbinds(reader: _BerReader) -> list[dict[str, Any]]:
    tag, body = reader.read_tlv()
    if tag != 0x30:
        raise TrapDecodeError("varbind list is not a SEQUENCE")
    items = _BerReader(body)
    binds: list[dict[str, Any]] = []
    while items.remaining() > 0:
        bind_tag, bind_body = items.read_tlv()
        if bind_tag != 0x30:
            raise TrapDecodeError("varbind is not a SEQUENCE")
        bind = _BerReader(bind_body)
        oid = _oid_to_string(_read_raw_oid(bind))
        value = _read_value(bind)
        binds.append({"oid": oid, "value": value})
    return binds


def _read_integer(reader: _BerReader) -> int:
    tag, value = reader.read_tlv()
    if tag != 0x02:
        raise TrapDecodeError("expected INTEGER")
    return int.from_bytes(value, "big", signed=True)


def _read_octet(reader: _BerReader) -> str:
    tag, value = reader.read_tlv()
    if tag != 0x04:
        raise TrapDecodeError("expected OCTET STRING")
    return value.decode("latin-1", errors="replace")


def _read_raw_oid(reader: _BerReader) -> bytes:
    tag, value = reader.read_tlv()
    if tag != 0x06:
        raise TrapDecodeError("expected OBJECT IDENTIFIER")
    return value


def _read_ip(reader: _BerReader) -> bytes:
    tag, value = reader.read_tlv()
    if tag not in {0x40, 0x04} or len(value) != 4:
        raise TrapDecodeError("expected IpAddress")
    return value


def _read_timeticks(reader: _BerReader) -> int:
    tag, value = reader.read_tlv()
    if tag not in {0x43, 0x02}:
        raise TrapDecodeError("expected TimeTicks")
    return int.from_bytes(value, "big")


def _read_value(reader: _BerReader) -> Any:
    tag, value = reader.read_tlv()
    if tag == 0x05:
        return None
    if tag == 0x02:
        return int.from_bytes(value, "big", signed=True)
    if tag in {0x41, 0x42, 0x43, 0x46}:
        return int.from_bytes(value, "big", signed=False)
    if tag == 0x06:
        return _oid_to_string(value)
    if tag == 0x40 and len(value) == 4:
        return _format_ip(value)
    if tag == 0x04:
        try:
            text = value.decode("utf-8")
            if text.isprintable():
                return text
        except UnicodeDecodeError:
            pass
        return value.hex()
    return value.hex()


def _oid_to_string(raw: bytes) -> str:
    if not raw:
        return ""
    first = raw[0]
    parts = [str(first // 40), str(first % 40)]
    value = 0
    for byte in raw[1:]:
        value = (value << 7) | (byte & 0x7F)
        if byte & 0x80 == 0:
            parts.append(str(value))
            value = 0
    return ".".join(parts)


def _format_ip(raw: bytes) -> str:
    return ".".join(str(part) for part in raw)


def _v1_trap_oid(enterprise: str, generic: int, specific: int) -> str:
    if 0 <= generic <= 5:
        return f"1.3.6.1.6.3.1.1.5.{generic + 1}"
    return f"{enterprise}.0.{specific}"


def encode_snmp_v2_trap(community: str, varbinds: list[dict[str, Any]], request_id: int = 1) -> bytes:
    encoded_binds = b"".join(_encode_varbind(item) for item in varbinds)
    pdu = (
        _encode_integer(request_id)
        + _encode_integer(0)
        + _encode_integer(0)
        + _tlv(0x30, encoded_binds)
    )
    message = _encode_integer(1) + _tlv(0x04, community.encode("latin-1")) + _tlv(0xA7, pdu)
    return _tlv(0x30, message)


def _encode_varbind(item: dict[str, Any]) -> bytes:
    oid = _encode_oid(str(item.get("oid") or ""))
    value = item.get("value")
    if isinstance(value, int):
        encoded_value = _encode_integer(value)
    elif value is None:
        encoded_value = _tlv(0x05, b"")
    else:
        text = str(value)
        if text.replace(".", "").isdigit() and "." in text:
            encoded_value = _tlv(0x06, _oid_to_bytes(text))
        else:
            encoded_value = _tlv(0x04, text.encode("utf-8"))
    return _tlv(0x30, oid + encoded_value)


def _encode_integer(value: int) -> bytes:
    if value == 0:
        raw = b"\x00"
    else:
        length = (value.bit_length() + 8) // 8
        raw = value.to_bytes(length, "big", signed=True)
        if value > 0 and raw[0] & 0x80:
            raw = b"\x00" + raw
    return _tlv(0x02, raw)


def _encode_oid(oid: str) -> bytes:
    return _tlv(0x06, _oid_to_bytes(oid))


def _oid_to_bytes(oid: str) -> bytes:
    parts = [int(part) for part in oid.split(".") if part]
    if len(parts) < 2:
        raise TrapDecodeError("invalid oid")
    raw = bytes([40 * parts[0] + parts[1]])
    for part in parts[2:]:
        if part < 0:
            raise TrapDecodeError("invalid oid")
        stack = [part & 0x7F]
        part >>= 7
        while part:
            stack.append(0x80 | (part & 0x7F))
            part >>= 7
        raw += bytes(reversed(stack))
    return raw


def _tlv(tag: int, value: bytes) -> bytes:
    length = len(value)
    if length < 0x80:
        encoded_length = bytes([length])
    else:
        raw = length.to_bytes((length.bit_length() + 7) // 8, "big")
        encoded_length = bytes([0x80 | len(raw)]) + raw
    return bytes([tag]) + encoded_length + value
