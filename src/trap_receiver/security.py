from __future__ import annotations

import ipaddress
import time
from collections import defaultdict, deque
from typing import Iterable


class Allowlist:
    def __init__(self, cidrs: Iterable[str] | None = None, extra_hosts: Iterable[str] | None = None):
        self.networks = []
        for raw in cidrs or []:
            text = str(raw).strip()
            if not text:
                continue
            self.networks.append(ipaddress.ip_network(text, strict=False))
        self.hosts = set()
        for raw in extra_hosts or []:
            text = str(raw).strip()
            if not text:
                continue
            self.hosts.add(str(ipaddress.ip_address(text)))

    def allows(self, source_ip: str) -> bool:
        try:
            address = ipaddress.ip_address(source_ip)
        except ValueError:
            return False
        if str(address) in self.hosts:
            return True
        if not self.networks and not self.hosts:
            return False
        return any(address in network for network in self.networks)


class SlidingWindowRateLimiter:
    def __init__(self, limit: int, window_seconds: float):
        self.limit = max(1, int(limit))
        self.window_seconds = max(0.1, float(window_seconds))
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str, now: float | None = None) -> bool:
        current = now if now is not None else time.monotonic()
        bucket = self._hits[key]
        cutoff = current - self.window_seconds
        while bucket and bucket[0] <= cutoff:
            bucket.popleft()
        if len(bucket) >= self.limit:
            return False
        bucket.append(current)
        return True


def parse_csv(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [item.strip() for item in str(raw).split(",") if item.strip()]


def parse_allowlist(raw: str | None) -> list[str]:
    seen: list[str] = []
    known: set[str] = set()
    for line in str(raw or "").replace(",", "\n").splitlines():
        item = line.strip()
        if item == "" or item.startswith("#"):
            continue
        try:
            network = ipaddress.ip_network(item, strict=False)
        except ValueError:
            raise ValueError(f"Rede inválida: {item}.") from None
        rendered = str(network)
        if rendered in known:
            continue
        known.add(rendered)
        seen.append(rendered)
    if not seen:
        raise ValueError("Informe ao menos uma rede ou IP.")
    return seen
