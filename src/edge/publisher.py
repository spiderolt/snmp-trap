from __future__ import annotations

import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class PublishError(RuntimeError):
    pass


def publish_event(url: str, token: str, payload: dict[str, object], *, timeout: float = 10) -> None:
    body = json.dumps(payload).encode("utf-8")
    request = Request(
        url,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "SpiderOLT-snmp-trap/1.0",
        },
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            if response.status >= 300:
                raise PublishError(f"API respondeu {response.status}")
    except HTTPError as exc:
        raise PublishError(f"API respondeu {exc.code}") from exc
    except URLError as exc:
        raise PublishError(str(exc.reason)) from exc
