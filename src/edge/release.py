from __future__ import annotations

import json
import os
import re
import threading
import time
from dataclasses import dataclass
from urllib.error import URLError
from urllib.request import Request, urlopen

_VERSION = re.compile(r"^v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(\.(0|[1-9][0-9]*))?$")
_REPO = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
_CACHE_TTL = 600
_ERROR_TTL = 30
_lock = threading.Lock()
_cache: tuple[float, str | None, str] | None = None


class UpdateError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ReleaseStatus:
    current: str
    latest: str | None = None

    @property
    def update_available(self) -> bool:
        return self.latest is not None and is_newer(self.latest, self.current)


def current_version() -> str:
    value = os.environ.get("SNMP_TRAP_VERSION", "dev").strip()
    return value or "dev"


def repo() -> str:
    value = os.environ.get("SNMP_TRAP_REPO", "spiderolt/snmp-trap").strip()
    if _REPO.fullmatch(value) is None:
        return "spiderolt/snmp-trap"
    return value


def parse_version(value: str) -> tuple[int, int, int] | None:
    match = _VERSION.fullmatch(value.strip())
    if match is None:
        return None
    return (int(match.group(1)), int(match.group(2)), int(match.group(4) or 0))


def is_newer(latest: str, current: str) -> bool:
    parsed_latest = parse_version(latest)
    parsed_current = parse_version(current)
    if parsed_latest is None or parsed_current is None:
        return False
    return parsed_latest > parsed_current


def fetch_latest_tag(repository: str, *, timeout: float = 2) -> str:
    if _REPO.fullmatch(repository) is None:
        raise OSError("repositório inválido")
    request = Request(
        f"https://api.github.com/repos/{repository}/releases/latest",
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "SpiderOLT-snmp-trap",
        },
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, URLError, json.JSONDecodeError, ValueError) as exc:
        raise OSError("release indisponível") from exc
    if not isinstance(payload, dict):
        raise OSError("tag inválida")
    tag = str(payload.get("tag_name") or "").strip()
    if parse_version(tag) is None:
        raise OSError("tag inválida")
    return tag


def cached_latest() -> str | None:
    global _cache
    now = time.monotonic()
    with _lock:
        cached = _cache
    if cached is not None and cached[2] == "ok" and now - cached[0] < _CACHE_TTL:
        return cached[1]
    if cached is not None and cached[2] == "error" and now - cached[0] < _ERROR_TTL:
        return None
    try:
        tag = fetch_latest_tag(repo())
    except OSError:
        with _lock:
            _cache = (now, None, "error")
        return None
    with _lock:
        _cache = (now, tag, "ok")
    return tag


def clear_release_cache() -> None:
    global _cache
    with _lock:
        _cache = None


def release_status() -> ReleaseStatus:
    current = current_version()
    if parse_version(current) is None:
        return ReleaseStatus(current=current, latest=None)
    try:
        latest = cached_latest()
    except Exception:
        latest = None
    return ReleaseStatus(current=current, latest=latest)


def confirm_latest(requested: str) -> str:
    requested = requested.strip()
    if parse_version(requested) is None:
        raise UpdateError("Versão inválida.")
    if not is_newer(requested, current_version()):
        raise UpdateError("Esta já é a versão mais nova.")
    try:
        latest = fetch_latest_tag(repo())
    except OSError as exc:
        raise UpdateError("Não foi possível confirmar o release mais recente.") from exc
    if latest != requested:
        raise UpdateError("A versão disponível mudou. Atualize a página.")
    return latest
