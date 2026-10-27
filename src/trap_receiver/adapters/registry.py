from __future__ import annotations

from typing import Any, Iterable, Optional

from trap_receiver.adapters.base import TrapAdapter
from trap_receiver.adapters.huawei_ma5600 import HuaweiMA5600TrapAdapter
from trap_receiver.contract import DecodeResult


class TrapAdapterRegistry:
    def __init__(self, adapters: Iterable[TrapAdapter] | None = None):
        self._adapters = list(adapters or [])

    def register(self, adapter: TrapAdapter) -> None:
        self._adapters.append(adapter)

    def decode(
        self,
        *,
        source_ip: str,
        olt_id: Optional[int],
        varbinds: list[dict[str, Any]],
        received_at: str,
        community_present: bool = False,
        trap_oid: str | None = None,
    ) -> DecodeResult:
        for adapter in self._adapters:
            if adapter.matches(trap_oid, varbinds):
                return adapter.decode(
                    source_ip=source_ip,
                    olt_id=olt_id,
                    varbinds=varbinds,
                    received_at=received_at,
                    community_present=community_present,
                )
        return DecodeResult.quarantine("unsupported_vendor", trap_oid=trap_oid, raw_varbinds=varbinds)


def default_registry() -> TrapAdapterRegistry:
    return TrapAdapterRegistry([HuaweiMA5600TrapAdapter()])
