from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Optional

from trap_receiver.contract import DecodeResult


class TrapAdapter(ABC):
    """Vendor-specific SNMP trap normalizer.

    Future vendors implement this interface and register in the adapter registry.
    """

    vendor: str

    @abstractmethod
    def matches(self, trap_oid: str | None, varbinds: list[dict[str, Any]]) -> bool:
        raise NotImplementedError

    @abstractmethod
    def decode(
        self,
        *,
        source_ip: str,
        olt_id: Optional[int],
        varbinds: list[dict[str, Any]],
        received_at: str,
        community_present: bool = False,
    ) -> DecodeResult:
        raise NotImplementedError
