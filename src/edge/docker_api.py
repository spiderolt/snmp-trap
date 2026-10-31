from __future__ import annotations

import json
import os
import socket
from http.client import HTTPConnection
from urllib.parse import quote, urlencode


class DockerError(RuntimeError):
    pass


def docker_socket() -> str:
    return os.environ.get("SNMP_TRAP_DOCKER_SOCKET", "/var/run/docker.sock")


class DockerClient:
    def __init__(self, socket_path: str | None = None) -> None:
        self.socket_path = socket_path or docker_socket()

    def inspect(self, container_id: str) -> dict[str, object]:
        status, body = self._request("GET", f"/v1.41/containers/{quote(container_id, safe='')}/json")
        if status != 200:
            raise DockerError(_message(body) or f"container {container_id} indisponível")
        payload = json.loads(body.decode("utf-8"))
        if not isinstance(payload, dict):
            raise DockerError("resposta inválida do Docker")
        return payload

    def find_named(self, name: str) -> dict[str, object] | None:
        query = urlencode({"all": "1", "filters": json.dumps({"name": [name]})})
        status, body = self._request("GET", f"/v1.41/containers/json?{query}")
        if status != 200:
            raise DockerError(_message(body) or "não foi possível listar os containers")
        payload = json.loads(body.decode("utf-8"))
        if not isinstance(payload, list):
            raise DockerError("resposta inválida do Docker")
        wanted = f"/{name}"
        for item in payload:
            if isinstance(item, dict) and wanted in (item.get("Names") or []):
                return item
        return None

    def pull(self, image: str) -> None:
        name, tag = image.rsplit(":", 1)
        query = urlencode({"fromImage": name, "tag": tag})
        status, body = self._request(
            "POST",
            f"/v1.41/images/create?{query}",
            timeout=600,
            headers={"X-Registry-Auth": "e30="},
        )
        if status >= 300:
            raise DockerError(_message(body) or f"não foi possível baixar {image}")
        for line in body.splitlines():
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict) and item.get("error"):
                raise DockerError(str(item["error"]))

    def create(self, name: str, body: dict[str, object]) -> str:
        status, payload = self._request(
            "POST",
            f"/v1.41/containers/create?{urlencode({'name': name})}",
            body=json.dumps(body).encode("utf-8"),
        )
        if status != 201:
            raise DockerError(_message(payload) or f"não foi possível criar {name}")
        created = json.loads(payload.decode("utf-8"))
        container_id = str(created.get("Id") or "")
        if container_id == "":
            raise DockerError(f"não foi possível criar {name}")
        return container_id

    def start(self, container_id: str) -> None:
        self._expect("POST", f"/v1.41/containers/{quote(container_id, safe='')}/start", ok=(204, 304))

    def stop(self, container_id: str) -> None:
        self._expect("POST", f"/v1.41/containers/{quote(container_id, safe='')}/stop?t=15", ok=(204, 304))

    def rename(self, container_id: str, name: str) -> None:
        query = urlencode({"name": name})
        self._expect("POST", f"/v1.41/containers/{quote(container_id, safe='')}/rename?{query}", ok=(204,))

    def remove(self, container_id: str) -> None:
        self._expect("DELETE", f"/v1.41/containers/{quote(container_id, safe='')}?force=1", ok=(204,))

    def remove_named(self, name: str) -> None:
        found = self.find_named(name)
        if found is None:
            return
        container_id = str(found.get("Id") or "")
        if container_id:
            self.remove(container_id)

    def remove_old_images(self, *, keep: str) -> None:
        status, body = self._request("GET", "/v1.41/images/json")
        if status != 200:
            raise DockerError(_message(body) or "não foi possível listar as imagens")
        payload = json.loads(body.decode("utf-8"))
        if not isinstance(payload, list):
            raise DockerError("resposta inválida do Docker")
        for tag in old_agent_tags(payload, keep=keep):
            code, _payload = self._request("DELETE", f"/v1.41/images/{quote(tag, safe='')}")
            if code not in {200, 404, 409}:
                raise DockerError(f"não foi possível remover {tag}")

    def _expect(self, method: str, path: str, *, ok: tuple[int, ...]) -> None:
        status, body = self._request(method, path)
        if status not in ok:
            raise DockerError(_message(body) or f"Docker respondeu {status}")

    def _request(
        self,
        method: str,
        path: str,
        *,
        body: bytes | None = None,
        timeout: float = 60,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, bytes]:
        connection = HTTPConnection("localhost", timeout=timeout)
        host = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        host.settimeout(timeout)
        try:
            host.connect(self.socket_path)
        except PermissionError as exc:
            host.close()
            raise DockerError("sem permissão para usar o Docker") from exc
        except OSError as exc:
            host.close()
            raise DockerError("socket do Docker indisponível") from exc
        connection.sock = host
        request_headers = {"Host": "localhost", **(headers or {})}
        if body is not None:
            request_headers["Content-Type"] = "application/json"
        try:
            connection.request(method, path, body=body, headers=request_headers)
            response = connection.getresponse()
            return response.status, response.read()
        except OSError as exc:
            raise DockerError("socket do Docker indisponível") from exc
        finally:
            connection.close()


def old_agent_tags(images: list[object], *, keep: str) -> list[str]:
    prefix = keep.rsplit(":", 1)[0] + ":"
    found: list[str] = []
    for image in images:
        if not isinstance(image, dict):
            continue
        for tag in image.get("RepoTags") or []:
            if isinstance(tag, str) and tag.startswith(prefix) and tag != keep:
                found.append(tag)
    return found


def _message(body: bytes) -> str:
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return body.decode("utf-8", errors="replace")[:240]
    if isinstance(payload, dict) and payload.get("message"):
        return str(payload["message"])[:240]
    return ""
