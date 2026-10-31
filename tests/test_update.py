from __future__ import annotations

import json

import pytest

from edge.docker_api import DockerClient, DockerError, old_agent_tags
from edge.release import (
    UpdateError,
    clear_release_cache,
    confirm_latest,
    fetch_latest_tag,
    is_newer,
    release_status,
    repo,
)
from edge.update import (
    apply_update,
    image_ref,
    prune_after_successful_update,
    read_image_env,
    read_status,
    replace_service,
    replacement_body,
    rewrite_image_env,
    start_update,
    updater_binds,
)


class _Response:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload

    def read(self) -> bytes:
        return self.payload

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *args: object) -> bool:
        return False


def test_versions_compare_as_numbers() -> None:
    assert is_newer("v1.10.0", "v1.9.0")
    assert is_newer("v1.2.1", "v1.2")
    assert not is_newer("v1.2", "v1.2.0")
    assert not is_newer("v1.2.0", "dev")
    assert not is_newer("latest", "v1.0.0")


def test_image_uses_the_repository_owner(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SNMP_TRAP_REPO", "SpiderOLT/snmp-trap")
    assert image_ref("v1.2.0") == "ghcr.io/spiderolt/snmp-trap:v1.2.0"
    monkeypatch.setenv("SNMP_TRAP_REPO", "https://evil.example")
    assert repo() == "spiderolt/snmp-trap"
    with pytest.raises(UpdateError):
        image_ref("v1")


def test_release_status_reads_a_real_version_and_caches_it(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SNMP_TRAP_VERSION", "v1.0.3")
    clear_release_cache()
    calls = {"count": 0}

    def fake_fetch(repository: str, *, timeout: float = 2) -> str:
        calls["count"] += 1
        assert repository == "spiderolt/snmp-trap"
        return "v1.0.3"

    monkeypatch.setattr("edge.release.fetch_latest_tag", fake_fetch)
    first = release_status()
    second = release_status()
    assert first.current == "v1.0.3"
    assert first.latest == "v1.0.3"
    assert not first.update_available
    assert second.latest == "v1.0.3"
    assert calls["count"] == 1


def test_dev_version_does_not_check_github(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SNMP_TRAP_VERSION", "dev")

    def fail(repository: str, *, timeout: float = 2) -> str:
        raise AssertionError(repository)

    monkeypatch.setattr("edge.release.fetch_latest_tag", fail)
    status = release_status()
    assert status.current == "dev"
    assert status.latest is None
    assert not status.update_available


def test_fetch_latest_tag_reads_the_github_release(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_urlopen(request, timeout=0):  # noqa: ANN001
        assert request.full_url == "https://api.github.com/repos/spiderolt/snmp-trap/releases/latest"
        return _Response(b'{"tag_name":"v1.2.3"}')

    monkeypatch.setattr("edge.release.urlopen", fake_urlopen)
    assert fetch_latest_tag("spiderolt/snmp-trap") == "v1.2.3"
    with pytest.raises(OSError):
        fetch_latest_tag("not a repo")


def test_confirm_latest_rejects_a_version_other_than_the_release(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SNMP_TRAP_VERSION", "v1.0.1")
    monkeypatch.setattr("edge.release.fetch_latest_tag", lambda repository, timeout=2: "v1.0.2")
    assert confirm_latest("v1.0.2") == "v1.0.2"
    with pytest.raises(UpdateError, match="mudou"):
        confirm_latest("v9.0.0")
    with pytest.raises(UpdateError, match="mais nova"):
        confirm_latest("v1.0.1")


def test_env_file_replaces_only_the_image_line(tmp_path) -> None:
    env = tmp_path / ".env"
    env.write_text("OTHER=1\nSNMP_TRAP_IMAGE=old\n", encoding="utf-8")
    rewrite_image_env(tmp_path, "ghcr.io/spiderolt/snmp-trap:v1.0.2")
    assert read_image_env(tmp_path) == "ghcr.io/spiderolt/snmp-trap:v1.0.2"
    assert env.read_text(encoding="utf-8") == "OTHER=1\nSNMP_TRAP_IMAGE=ghcr.io/spiderolt/snmp-trap:v1.0.2\n"


def test_replacement_keeps_compose_settings_and_drops_the_old_version() -> None:
    body = replacement_body(_service_spec(), "ghcr.io/spiderolt/snmp-trap:v1.0.2")
    assert body["Image"] == "ghcr.io/spiderolt/snmp-trap:v1.0.2"
    assert body["Env"] == ["SNMP_TRAP_HTTP_PORT=8088"]
    assert body["Labels"]["com.docker.compose.image"] == "ghcr.io/spiderolt/snmp-trap:v1.0.2"
    assert body["HostConfig"]["NetworkMode"] == "host"
    assert "Cmd" not in body


def test_updater_binds_add_the_socket_and_the_install_directory(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SNMP_TRAP_CONFIG_PATH", "/var/lib/snmp-trap/config.json")
    binds = updater_binds(_service_spec(), project="/opt/snmp-trap", socket_path="/var/run/docker.sock")
    assert "/var/lib/snmp-trap:/var/lib/snmp-trap" in binds
    assert "/var/run/docker.sock:/var/run/docker.sock" in binds
    assert "/opt/snmp-trap:/opt/snmp-trap" in binds


def test_old_images_of_this_agent_are_removed_and_other_images_stay() -> None:
    images = [
        {"RepoTags": ["ghcr.io/spiderolt/snmp-trap:v1.0.1", "ghcr.io/spiderolt/snmp-trap:v1.0.0"]},
        {"RepoTags": ["ghcr.io/spiderolt/snmp-trap:v1.0.2"]},
        {"RepoTags": ["zabbix/zabbix-server:latest"]},
        {"RepoTags": None},
    ]
    assert old_agent_tags(images, keep="ghcr.io/spiderolt/snmp-trap:v1.0.2") == [
        "ghcr.io/spiderolt/snmp-trap:v1.0.1",
        "ghcr.io/spiderolt/snmp-trap:v1.0.0",
    ]


def test_replace_rolls_back_when_the_new_container_does_not_start() -> None:
    docker = _FakeDocker(fail_start=True)
    with pytest.raises(UpdateError, match="boom"):
        replace_service(docker, "old", "ghcr.io/spiderolt/snmp-trap:v1.0.2")
    assert docker.calls == [
        "inspect",
        "remove_named:snmp-trap-snmp-trap-1-previous",
        "remove_named:snmp-trap-snmp-trap-1-next",
        "create:snmp-trap-snmp-trap-1-next",
        "stop:old",
        "rename:old:snmp-trap-snmp-trap-1-previous",
        "rename:new:snmp-trap-snmp-trap-1",
        "start:new",
        "rename:new:snmp-trap-snmp-trap-1-next",
        "rename:old:snmp-trap-snmp-trap-1",
        "start:old",
        "remove:new",
    ]


def test_replace_removes_the_stopped_container() -> None:
    docker = _FakeDocker(fail_start=False)
    replace_service(docker, "old", "ghcr.io/spiderolt/snmp-trap:v1.0.2")
    assert docker.calls[-2:] == ["start:new", "remove:old"]
    assert docker.body["Image"] == "ghcr.io/spiderolt/snmp-trap:v1.0.2"


def test_start_update_launches_one_job(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    socket_path = tmp_path / "docker.sock"
    socket_path.write_text("", encoding="utf-8")
    monkeypatch.setenv("SNMP_TRAP_CONFIG_PATH", str(tmp_path / "config.json"))
    monkeypatch.setenv("SNMP_TRAP_PROJECT_DIR", "/opt/snmp-trap")
    docker = _JobDocker(str(socket_path))
    start_update("v1.0.2", client=docker, service_id="abc")
    name, body = docker.created[0]
    assert name == "snmp-trap-update"
    assert body["Entrypoint"] == ["python", "-m", "edge.update"]
    assert body["Cmd"] == ["v1.0.2", "abc"]
    assert body["HostConfig"]["AutoRemove"] is True
    assert body["HostConfig"]["NetworkMode"] == "bridge"
    assert docker.started == ["job-id"]
    assert read_status()["state"] == "running"


def test_start_update_refuses_a_second_job(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    socket_path = tmp_path / "docker.sock"
    socket_path.write_text("", encoding="utf-8")
    monkeypatch.setenv("SNMP_TRAP_PROJECT_DIR", "/opt/snmp-trap")
    docker = _JobDocker(str(socket_path), running=True)
    with pytest.raises(UpdateError, match="em andamento"):
        start_update("v1.0.2", client=docker, service_id="abc")
    assert docker.created == []


def test_apply_update_pins_the_new_image_and_restores_it_on_failure(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    env = tmp_path / ".env"
    env.write_text("SNMP_TRAP_IMAGE=ghcr.io/spiderolt/snmp-trap:v1.0.1\nOTHER=1\n", encoding="utf-8")
    monkeypatch.setattr("edge.update.project_dir", lambda: tmp_path)
    monkeypatch.setenv("SNMP_TRAP_CONFIG_PATH", str(tmp_path / "config.json"))
    seen: dict[str, str] = {}

    class Client:
        def pull(self, image: str) -> None:
            seen["pulled"] = image

        def remove_old_images(self, *, keep: str) -> None:
            seen["keep"] = keep

    monkeypatch.setattr(
        "edge.update.replace_service",
        lambda client, service_id, image: seen.setdefault("replaced", image),
    )
    apply_update("v1.0.2", "abc", client=Client())
    assert seen == {
        "pulled": "ghcr.io/spiderolt/snmp-trap:v1.0.2",
        "replaced": "ghcr.io/spiderolt/snmp-trap:v1.0.2",
        "keep": "ghcr.io/spiderolt/snmp-trap:v1.0.2",
    }
    assert "SNMP_TRAP_IMAGE=ghcr.io/spiderolt/snmp-trap:v1.0.2" in env.read_text(encoding="utf-8")
    assert "OTHER=1" in env.read_text(encoding="utf-8")
    assert read_status()["state"] == "succeeded"

    def fail(client, service_id: str, image: str) -> None:
        raise UpdateError("porta ocupada")

    monkeypatch.setattr("edge.update.replace_service", fail)
    with pytest.raises(UpdateError, match="porta ocupada"):
        apply_update("v1.0.3", "abc", client=Client())
    assert env.read_text(encoding="utf-8") == "SNMP_TRAP_IMAGE=ghcr.io/spiderolt/snmp-trap:v1.0.2\nOTHER=1\n"
    status = read_status()
    assert status["state"] == "failed"
    assert "porta ocupada" in status["error"]


def test_prune_waits_for_success_and_skips_a_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("edge.update.read_status", lambda: {"state": "failed"})
    monkeypatch.setattr("edge.update.time.sleep", lambda seconds: (_ for _ in ()).throw(AssertionError("sleep")))
    prune_after_successful_update()

    states = iter(["running", "succeeded"])
    slept: list[float] = []
    monkeypatch.setattr("edge.update.read_status", lambda: {"state": next(states)})
    monkeypatch.setattr("edge.update.time.sleep", lambda seconds: slept.append(seconds))
    monkeypatch.setattr("edge.update.docker_socket", lambda: "/missing/docker.sock")
    prune_after_successful_update()
    assert slept == [1, 5]


def test_pull_error_in_the_image_stream() -> None:
    class Client(DockerClient):
        def _request(self, method, path, *, body=None, timeout=60, headers=None):  # noqa: ANN001
            assert method == "POST"
            line = json.dumps({"error": "manifest desconhecido"}).encode("utf-8")
            return 200, line

    with pytest.raises(DockerError, match="manifest desconhecido"):
        Client().pull("ghcr.io/spiderolt/snmp-trap:v9.9.9")


def _service_spec() -> dict[str, object]:
    return {
        "Name": "/snmp-trap-snmp-trap-1",
        "Config": {
            "Image": "ghcr.io/spiderolt/snmp-trap:v1.0.1",
            "Env": [
                "SNMP_TRAP_VERSION=v1.0.1",
                "SNMP_TRAP_HTTP_PORT=8088",
                "PATH=/usr/local/bin",
            ],
            "Labels": {
                "com.docker.compose.image": "ghcr.io/spiderolt/snmp-trap:v1.0.1",
                "com.docker.compose.service": "snmp-trap",
            },
        },
        "HostConfig": {
            "Binds": ["/var/lib/snmp-trap:/var/lib/snmp-trap"],
            "NetworkMode": "host",
            "RestartPolicy": {"Name": "unless-stopped"},
        },
    }


class _FakeDocker:
    def __init__(self, *, fail_start: bool) -> None:
        self.fail_start = fail_start
        self.calls: list[str] = []
        self.body: dict[str, object] = {}
        self.spec = _service_spec()

    def inspect(self, container_id: str) -> dict[str, object]:
        self.calls.append("inspect")
        return self.spec

    def remove_named(self, name: str) -> None:
        self.calls.append(f"remove_named:{name}")

    def create(self, name: str, body: dict[str, object]) -> str:
        self.calls.append(f"create:{name}")
        self.body = body
        return "new"

    def stop(self, container_id: str) -> None:
        self.calls.append(f"stop:{container_id}")

    def rename(self, container_id: str, name: str) -> None:
        self.calls.append(f"rename:{container_id}:{name}")

    def start(self, container_id: str) -> None:
        self.calls.append(f"start:{container_id}")
        if self.fail_start and container_id == "new":
            raise DockerError("boom")

    def remove(self, container_id: str) -> None:
        self.calls.append(f"remove:{container_id}")


class _JobDocker(DockerClient):
    def __init__(self, socket_path: str, *, running: bool = False) -> None:
        super().__init__(socket_path)
        self.running = running
        self.created: list[tuple[str, dict[str, object]]] = []
        self.started: list[str] = []

    def inspect(self, container_id: str) -> dict[str, object]:
        return _service_spec()

    def find_named(self, name: str) -> dict[str, object] | None:
        if self.running:
            return {"Id": "job", "State": "running", "Names": [f"/{name}"]}
        return None

    def create(self, name: str, body: dict[str, object]) -> str:
        self.created.append((name, body))
        return "job-id"

    def start(self, container_id: str) -> None:
        self.started.append(container_id)
