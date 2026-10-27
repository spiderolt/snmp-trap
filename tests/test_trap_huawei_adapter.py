from __future__ import annotations

import json
from pathlib import Path

import pytest

from trap_receiver.adapters.huawei_ma5600 import HuaweiMA5600TrapAdapter
from trap_receiver.adapters.registry import default_registry
from trap_receiver.decoder import decode_snmp_trap, encode_snmp_v2_trap
from trap_receiver.security import Allowlist, SlidingWindowRateLimiter

FIXTURES = Path(__file__).parent / "fixtures" / "traps"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    "filename",
    [
        "huawei_onu_offline_los.json",
        "huawei_onu_offline_dying_gasp.json",
        "huawei_onu_online.json",
        "huawei_pon_down.json",
        "huawei_pon_up.json",
    ],
)
def test_huawei_adapter_normalizes_known_traps(filename: str):
    fixture = _load(filename)
    adapter = HuaweiMA5600TrapAdapter()
    result = adapter.decode(
        source_ip=fixture["source_ip"],
        olt_id=1,
        varbinds=fixture["varbinds"],
        received_at="2026-09-10T20:00:00Z",
        community_present=True,
    )
    assert result.status == "normalized"
    assert result.event is not None
    expected = fixture["expected"]
    assert result.event.event_type == expected["event_type"]
    assert result.event.reason == expected["reason"]
    assert result.event.pon_index == expected["pon_index"]
    assert result.event.onu_index == expected["onu_index"]
    assert result.event.vendor == "huawei_ma5600"


def test_unknown_oid_is_quarantined():
    fixture = _load("huawei_unknown_oid.json")
    result = HuaweiMA5600TrapAdapter().decode(
        source_ip=fixture["source_ip"],
        olt_id=1,
        varbinds=fixture["varbinds"],
        received_at="2026-09-10T20:00:00Z",
    )
    assert result.status == "quarantine"
    assert result.quarantine_reason == "unknown_trap_oid"


def test_missing_onu_index_is_quarantined():
    result = HuaweiMA5600TrapAdapter().decode(
        source_ip="10.10.1.8",
        olt_id=1,
        varbinds=[
            {"oid": "1.3.6.1.6.3.1.1.4.1.0", "value": "1.3.6.1.4.1.2011.6.128.2.1.4"},
        ],
        received_at="2026-09-10T20:00:00Z",
    )
    assert result.status == "quarantine"
    assert result.quarantine_reason == "unresolved_onu_index"


def test_registry_rejects_unknown_vendor():
    result = default_registry().decode(
        source_ip="10.0.0.1",
        olt_id=1,
        varbinds=[{"oid": "1.3.6.1.6.3.1.1.4.1.0", "value": "1.3.6.1.4.1.9999.1.1"}],
        received_at="2026-09-10T20:00:00Z",
        trap_oid="1.3.6.1.4.1.9999.1.1",
    )
    assert result.status == "quarantine"
    assert result.quarantine_reason == "unsupported_vendor"


def test_allowlist_and_rate_limiter():
    allowlist = Allowlist(["10.10.0.0/16"], extra_hosts=["192.0.2.8"])
    assert allowlist.allows("10.10.1.8")
    assert allowlist.allows("192.0.2.8")
    assert not allowlist.allows("8.8.8.8")
    assert not Allowlist().allows("10.10.1.8")

    limiter = SlidingWindowRateLimiter(2, 10)
    assert limiter.allow("10.10.1.8", now=1)
    assert limiter.allow("10.10.1.8", now=2)
    assert not limiter.allow("10.10.1.8", now=3)
    assert limiter.allow("10.10.1.8", now=12)


def test_decoder_reads_v2_trap_bytes():
    payload = encode_snmp_v2_trap(
        "public",
        [
            {"oid": "1.3.6.1.2.1.1.3.0", "value": 123},
            {"oid": "1.3.6.1.6.3.1.1.4.1.0", "value": "1.3.6.1.4.1.2011.6.128.2.1.4"},
        ],
    )
    decoded = decode_snmp_trap(payload)
    assert decoded.community == "public"
    assert decoded.pdu_type == "v2_trap"
    assert decoded.varbinds[0]["oid"] == "1.3.6.1.2.1.1.3.0"
    assert decoded.varbinds[1]["value"] == "1.3.6.1.4.1.2011.6.128.2.1.4"
