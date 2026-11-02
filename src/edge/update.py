from __future__ import annotations

import json
import os
import re
import sys
import threading
import time
from pathlib import Path

from edge.config import config_path
from edge.docker_api import DockerClient, DockerError, docker_socket
from edge.release import UpdateError, current_version, parse_version, repo

JOB_NAME = "snmp-trap-update"
_update_lock = threading.Lock()
_KEEP_ENV = {
    "SNMP_TRAP_CONFIG_PATH",
    "SNMP_TRAP_HTTP_PORT",
    "SNMP_TRAP_PROJECT_DIR",
    "SNMP_TRAP_REPO",
    "TRAP_ALLOWLIST_CIDRS",
}


def project_dir() -> Path:
    raw = os.environ.get("SNMP_TRAP_PROJECT_DIR", "/opt/snmp-trap").strip() or "/opt/snmp-trap"
    if not raw.startswith("/") or ":" in raw or "\n" in raw:
        raise UpdateError("Diretório da instalação inválido.")
    return Path(raw)


def image_ref(version: str, repository: str | None = None) -> str:
    if parse_version(version) is None:
        raise UpdateError("Versão inválida.")
    repository = repository or repo()
    owner = repository.split("/", 1)[0].lower()
    return f"ghcr.io/{owner}/snmp-trap:{version}"


def status_path() -> Path:
    return config_path().parent / "update-status.json"


def read_status() -> dict[str, str]:
    path = status_path()
    if not path.is_file():
        return {"state": "idle", "target": "", "error": ""}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"state": "unknown", "target": "", "error": ""}
    if not isinstance(raw, dict):
        return {"state": "unknown", "target": "", "error": ""}
    return {
        "state": str(raw.get("state") or "unknown"),
        "target": str(raw.get("target") or ""),
        "error": str(raw.get("error") or ""),
    }


def write_status(*, state: str, target: str, error: str = "") -> None:
    path = status_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps({"state": state, "target": target, "error": error}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def clear_status() -> None:
    try:
        status_path().unlink()
    except FileNotFoundError:
        return


def read_image_env(directory: Path) -> str | None:
    path = directory / ".env"
    if not path.is_file():
        raise UpdateError(f"Não encontrei a instalação em {directory}.")
    for row in path.read_text(encoding="utf-8").splitlines():
        if row.startswith("SNMP_TRAP_IMAGE="):
            return row.split("=", 1)[1]
    return None


def rewrite_image_env(directory: Path, image: str) -> None:
    path = directory / ".env"
    if not path.is_file():
        raise UpdateError(f"Não encontrei a instalação em {directory}.")
    rows = path.read_text(encoding="utf-8").splitlines()
    line = f"SNMP_TRAP_IMAGE={image}"
    replaced = False
    updated: list[str] = []
    for row in rows:
        if row.startswith("SNMP_TRAP_IMAGE="):
            updated.append(line)
            replaced = True
        else:
            updated.append(row)
    if not replaced:
        updated.append(line)
    temporary = path.with_suffix(".env.tmp")
    temporary.write_text("\n".join(updated) + "\n", encoding="utf-8")
    temporary.replace(path)


def preserved_env(spec: dict[str, object]) -> list[str]:
    config = spec.get("Config")
    env = config.get("Env") if isinstance(config, dict) else None
    kept: list[str] = []
    for item in env or []:
        if not isinstance(item, str) or "=" not in item:
            continue
        name, _value = item.split("=", 1)
        if name in _KEEP_ENV:
            kept.append(item)
    return kept


def preserved_labels(spec: dict[str, object], image: str) -> dict[str, str]:
    config = spec.get("Config")
    raw = config.get("Labels") if isinstance(config, dict) else None
    if not isinstance(raw, dict):
        return {}
    labels = {str(key): str(value) for key, value in raw.items() if value is not None}
    if "com.docker.compose.image" in labels:
        labels["com.docker.compose.image"] = image
    return labels


def preserved_binds(spec: dict[str, object]) -> list[str]:
    host = spec.get("HostConfig")
    host_config = host if isinstance(host, dict) else {}
    binds = [item for item in (host_config.get("Binds") or []) if isinstance(item, str) and item]
    if binds:
        return binds
    collected: list[str] = []
    for mount in host_config.get("Mounts") or []:
        if not isinstance(mount, dict) or mount.get("Type") != "bind":
            continue
        source = mount.get("Source")
        destination = mount.get("Destination")
        if not isinstance(source, str) or not isinstance(destination, str):
            continue
        suffix = ":ro" if mount.get("RW") is False else ""
        collected.append(f"{source}:{destination}{suffix}")
    return collected


def replacement_body(spec: dict[str, object], image: str) -> dict[str, object]:
    host = spec.get("HostConfig")
    host_config = host if isinstance(host, dict) else {}
    restart = host_config.get("RestartPolicy")
    if not isinstance(restart, dict):
        restart = {"Name": "unless-stopped"}
    network = host_config.get("NetworkMode")
    return {
        "Image": image,
        "Env": preserved_env(spec),
        "Labels": preserved_labels(spec, image),
        "HostConfig": {
            "Binds": preserved_binds(spec),
            "NetworkMode": network if isinstance(network, str) and network else "host",
            "RestartPolicy": restart,
        },
    }


def updater_binds(spec: dict[str, object], *, project: str, socket_path: str) -> list[str]:
    binds = list(preserved_binds(spec))
    destinations = {bind_destination(item) for item in binds}
    required = [
        f"{socket_path}:{socket_path}",
        f"{project}:{project}",
        f"{config_path().parent}:{config_path().parent}",
    ]
    for item in required:
        destination = bind_destination(item)
        if destination not in destinations:
            binds.append(item)
            destinations.add(destination)
    return binds


def bind_destination(bind: str) -> str:
    parts = bind.split(":")
    if len(parts) >= 2:
        return parts[1]
    return ""


_CONTAINER_MARKERS = (
    re.compile(r"/containers/([0-9a-f]{64})/"),
    re.compile(r"docker-([0-9a-f]{64})\.scope"),
    re.compile(r"libpod-([0-9a-f]{64})\.scope"),
)
_HEX_HOSTNAME = re.compile(r"^[0-9a-f]{12,64}$")


def container_id_from_runtime(mountinfo: str, cgroup: str, hostname: str) -> str:
    for text in (mountinfo, cgroup):
        for pattern in _CONTAINER_MARKERS:
            found = pattern.search(text)
            if found:
                return found.group(1)
    if _HEX_HOSTNAME.fullmatch(hostname.strip().lower()):
        return hostname.strip().lower()
    return ""


def _read_runtime_file(path: str) -> str:
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def agent_container_id(containers: list[object]) -> str:
    matches: list[str] = []
    for item in containers:
        if not isinstance(item, dict) or str(item.get("State") or "") != "running":
            continue
        names = [str(name).lstrip("/") for name in (item.get("Names") or []) if isinstance(name, str)]
        if JOB_NAME in names:
            continue
        image_name = str(item.get("Image") or "").rsplit("/", 1)[-1]
        labels = item.get("Labels") if isinstance(item.get("Labels"), dict) else {}
        service = str(labels.get("com.docker.compose.service") or "")
        if service != "snmp-trap" and not image_name.startswith(("snmp-trap:", "snmp-trap@")):
            continue
        container_id = str(item.get("Id") or "")
        if container_id:
            matches.append(container_id)
    if len(matches) > 1:
        raise UpdateError("Há mais de um container deste agente em execução.")
    if len(matches) == 1:
        return matches[0]
    return ""


def service_container_id(client: DockerClient | None = None) -> str:
    configured = os.environ.get("SNMP_TRAP_CONTAINER_ID", "").strip()
    if configured:
        return configured
    candidate = container_id_from_runtime(
        _read_runtime_file("/proc/self/mountinfo"),
        _read_runtime_file("/proc/self/cgroup"),
        _read_runtime_file("/etc/hostname"),
    )
    if candidate and client is not None:
        try:
            client.inspect(candidate)
        except DockerError:
            candidate = ""
    if candidate:
        return candidate
    if client is not None:
        found = agent_container_id(client.list_containers())
        if found:
            return found
    raise UpdateError("Não identifiquei o container deste agente.")


def start_update(version: str, *, client: DockerClient | None = None, service_id: str | None = None) -> None:
    if parse_version(version) is None:
        raise UpdateError("Versão inválida.")
    project_dir()
    docker = client or DockerClient()
    if not Path(docker.socket_path).exists():
        raise UpdateError(
            "Não encontrei o Docker neste agente. "
            "Rode o script de instalação mais uma vez; depois disso a atualização fica nesta tela."
        )
    service_id = service_id or service_container_id(docker)
    with _update_lock:
        try:
            spec = docker.inspect(service_id)
            image = str((spec.get("Config") or {}).get("Image") or "")
            if image == "":
                raise UpdateError("Não identifiquei a imagem deste agente.")
            existing = docker.find_named(JOB_NAME)
            if existing is not None:
                if existing.get("State") == "running":
                    raise UpdateError("Uma atualização já está em andamento.")
                container_id = str(existing.get("Id") or "")
                if container_id:
                    docker.remove(container_id)
            write_status(state="running", target=version)
            job_id = docker.create(
                JOB_NAME,
                _updater_body(
                    spec,
                    image=image,
                    version=version,
                    service_id=service_id,
                    socket_path=docker.socket_path,
                ),
            )
            docker.start(job_id)
        except DockerError as exc:
            write_status(state="failed", target=version, error=str(exc))
            raise UpdateError(f"Não foi possível iniciar a atualização: {exc}") from exc


def apply_update(version: str, service_id: str, *, client: DockerClient | None = None) -> None:
    image = image_ref(version)
    env_path = project_dir() / ".env"
    if not env_path.is_file():
        raise UpdateError(f"Não encontrei a instalação em {env_path.parent}.")
    original = env_path.read_text(encoding="utf-8")
    write_status(state="running", target=version)
    docker = client or DockerClient()
    try:
        docker.pull(image)
        rewrite_image_env(env_path.parent, image)
        replace_service(docker, service_id, image)
        try:
            docker.remove_old_images(keep=image)
        except DockerError:
            pass
    except (UpdateError, DockerError, OSError) as exc:
        try:
            env_path.write_text(original, encoding="utf-8")
        except OSError:
            pass
        write_status(state="failed", target=version, error=str(exc))
        raise
    write_status(state="succeeded", target=version)


def replace_service(client: DockerClient, service_id: str, image: str) -> None:
    spec = client.inspect(service_id)
    name = spec.get("Name")
    original = str(name or "").lstrip("/")
    if original == "":
        raise UpdateError("Não identifiquei o nome do container.")
    previous = f"{original}-previous"
    nxt = f"{original}-next"
    client.remove_named(previous)
    client.remove_named(nxt)
    new_id = client.create(nxt, replacement_body(spec, image))
    client.stop(service_id)
    renamed_old = False
    renamed_new = False
    try:
        client.rename(service_id, previous)
        renamed_old = True
        client.rename(new_id, original)
        renamed_new = True
        client.start(new_id)
    except (DockerError, UpdateError) as exc:
        if renamed_new:
            try:
                client.rename(new_id, nxt)
            except DockerError:
                pass
        if renamed_old:
            try:
                client.rename(service_id, original)
            except DockerError:
                pass
        try:
            client.start(service_id)
        except DockerError:
            pass
        try:
            client.remove(new_id)
        except DockerError:
            pass
        raise UpdateError(f"Não foi possível iniciar a nova versão: {exc}") from exc
    try:
        client.remove(service_id)
    except DockerError:
        return


def prune_after_successful_update() -> None:
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        state = read_status().get("state")
        if state == "failed":
            return
        if state == "succeeded":
            break
        time.sleep(1)
    else:
        return
    time.sleep(5)
    if not Path(docker_socket()).exists():
        return
    try:
        DockerClient().remove_old_images(keep=image_ref(current_version()))
    except (DockerError, UpdateError):
        return
    clear_status()


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit(2)
    version, service_id = sys.argv[1], sys.argv[2]
    try:
        apply_update(version, service_id)
    except (UpdateError, DockerError, OSError) as exc:
        write_status(state="failed", target=version, error=str(exc))
        raise SystemExit(1) from exc


def _updater_body(
    spec: dict[str, object],
    *,
    image: str,
    version: str,
    service_id: str,
    socket_path: str,
) -> dict[str, object]:
    directory = str(project_dir())
    return {
        "Image": image,
        "Entrypoint": ["python", "-m", "edge.update"],
        "Cmd": [version, service_id],
        "Env": [
            f"SNMP_TRAP_REPO={repo()}",
            f"SNMP_TRAP_PROJECT_DIR={directory}",
            f"SNMP_TRAP_CONFIG_PATH={config_path()}",
            f"SNMP_TRAP_DOCKER_SOCKET={socket_path}",
            "PYTHONUNBUFFERED=1",
            "PYTHONPATH=/app",
        ],
        "Labels": {"snmp-trap.role": "update"},
        "HostConfig": {
            "Binds": updater_binds(spec, project=directory, socket_path=socket_path),
            "AutoRemove": True,
            "NetworkMode": "bridge",
            "RestartPolicy": {"Name": "no"},
        },
    }


if __name__ == "__main__":
    main()
