from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from trap_receiver.security import parse_allowlist

DEFAULT_PORT = 1162
DEFAULT_ALLOWLIST = "10.0.0.0/8,172.16.0.0/12,192.168.0.0/16"


@dataclass(slots=True)
class EdgeConfig:
    trap_port: int = DEFAULT_PORT
    api_host: str = ""
    token: str = ""
    allowlist: str = "\n".join(parse_allowlist(DEFAULT_ALLOWLIST))

    def to_dict(self) -> dict[str, object]:
        return {
            "trap_port": self.trap_port,
            "api_host": self.api_host,
            "token": self.token,
            "allowlist": self.allowlist,
        }


def config_path() -> Path:
    return Path(os.environ.get("SNMP_TRAP_CONFIG_PATH", "/var/lib/snmp-trap/config.json"))


def http_port() -> int:
    return _port(os.environ.get("SNMP_TRAP_HTTP_PORT", "8088"), fallback=8088)


def allowlist_cidrs() -> str:
    return os.environ.get("TRAP_ALLOWLIST_CIDRS", DEFAULT_ALLOWLIST)


def normalize_allowlist(raw: object, *, fallback: str | None = None) -> str:
    try:
        return "\n".join(parse_allowlist(str(raw if raw is not None else "")))
    except ValueError:
        if fallback is None:
            raise
        return "\n".join(parse_allowlist(fallback))


def load_config() -> EdgeConfig:
    path = config_path()
    if not path.exists():
        return EdgeConfig(allowlist=normalize_allowlist(allowlist_cidrs(), fallback=DEFAULT_ALLOWLIST))
    raw = json.loads(path.read_text(encoding="utf-8"))
    if "allowlist" in raw:
        try:
            allowlist = normalize_allowlist(raw.get("allowlist"))
        except ValueError:
            allowlist = normalize_allowlist(allowlist_cidrs(), fallback=DEFAULT_ALLOWLIST)
    else:
        allowlist = normalize_allowlist(allowlist_cidrs(), fallback=DEFAULT_ALLOWLIST)
    return EdgeConfig(
        trap_port=_port(raw.get("trap_port"), fallback=DEFAULT_PORT),
        api_host=str(raw.get("api_host") or "").strip(),
        token=str(raw.get("token") or "").strip(),
        allowlist=allowlist,
    )


def save_config(config: EdgeConfig) -> None:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(config.to_dict(), indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _port(value: object, *, fallback: int) -> int:
    try:
        port = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return fallback
    if 1 <= port <= 65535:
        return port
    return fallback
