from __future__ import annotations

from urllib.parse import urlparse

INGEST_PATH = "/api/snmp-trap/traps"


def ingest_url(raw: str) -> str:
    text = str(raw or "").strip()
    if text == "":
        raise ValueError("Informe o endereço da API.")
    if "://" not in text:
        text = f"https://{text}"
    parsed = urlparse(text)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Endereço da API inválido.")
    port = f":{parsed.port}" if parsed.port else ""
    return f"{parsed.scheme}://{parsed.hostname}{port}{INGEST_PATH}"
