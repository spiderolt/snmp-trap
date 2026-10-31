from __future__ import annotations

import json
import threading
from http.server import ThreadingHTTPServer
from urllib.request import Request, urlopen

from edge.config import EdgeConfig
from edge.listener import TrapListener
from edge.release import ReleaseStatus, UpdateError
from edge.web import health_body, make_handler, render, render_progress
from trap_receiver.security import Allowlist


def test_page_uses_the_spiderolt_shell() -> None:
    listener = TrapListener(allowlist=Allowlist())
    listener.stats.listening_port = 1162
    listener.set_config(EdgeConfig(trap_port=1162, api_host="site.spiderolt.com", token="edge_abc"))

    html = render(listener, message="Configuração salva.")

    assert "Spider<span>OLT</span>" in html
    assert 'src="/assets/logo.png"' in html
    assert 'src="/assets/logo-dark.png"' in html
    assert 'name="trap_port"' in html
    assert 'name="api_host"' in html
    assert 'name="token"' in html
    assert 'name="allowlist"' in html
    assert "10.0.0.0/8" in html
    assert "Um IP ou prefixo por linha." in html
    assert "continuam depois de reiniciar ou atualizar" in html
    assert 'value="site.spiderolt.com"' in html
    assert "Configuração salva." in html
    assert 'class="note ok"' in html
    assert 'id="open-update"' not in html
    assert "Versão " in html


def test_footer_offers_the_newer_release_behind_a_confirmation() -> None:
    listener = TrapListener(allowlist=Allowlist())
    html = render(listener, release=ReleaseStatus(current="v1.0.1", latest="v1.0.2"))

    assert "Versão v1.0.1" in html
    assert "v1.0.2 disponível" in html
    assert 'id="open-update"' in html
    assert "Confirmar atualização" in html
    assert 'name="version" value="v1.0.2"' in html
    assert "showModal()" in html
    assert 'id="cancel-update"' in html


def test_footer_hides_the_button_when_the_release_is_not_newer() -> None:
    listener = TrapListener(allowlist=Allowlist())
    html = render(listener, release=ReleaseStatus(current="v1.2.0", latest="v1.2.0"))
    assert "Versão v1.2.0" in html
    assert 'id="open-update"' not in html


def test_progress_page_waits_for_the_new_version() -> None:
    html = render_progress("v1.4.0")
    assert "Atualizando para v1.4.0" in html
    assert "/version=(\\S+)/" in html
    assert 'name="token"' not in html


def test_health_reports_the_running_version(monkeypatch) -> None:
    monkeypatch.setenv("SNMP_TRAP_VERSION", "v1.0.1")
    listener = TrapListener(allowlist=Allowlist())
    listener.stats.listening_port = 1162
    assert health_body(listener) == b"ok port=1162 version=v1.0.1\n"


def test_confirmed_update_starts_and_shows_progress(monkeypatch) -> None:
    started: list[str] = []
    monkeypatch.setattr("edge.web.confirm_latest", lambda requested: "v1.2.0")
    monkeypatch.setattr("edge.web.start_update", lambda version: started.append(version))
    listener = TrapListener(allowlist=Allowlist())
    listener.stats.listening_port = 1162
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(listener))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        request = Request(f"http://127.0.0.1:{port}/update", data=b"version=v1.2.0", method="POST")
        with urlopen(request, timeout=5) as response:
            html = response.read().decode("utf-8")
        with urlopen(f"http://127.0.0.1:{port}/healthz", timeout=5) as response:
            assert response.read() == health_body(listener)
        with urlopen(f"http://127.0.0.1:{port}/update-status", timeout=5) as response:
            assert json.loads(response.read().decode("utf-8"))["state"] == "idle"
    finally:
        server.shutdown()
        server.server_close()
    assert started == ["v1.2.0"]
    assert "Atualizando para v1.2.0" in html
    assert 'name="token"' not in html


def test_rejected_update_keeps_the_form(monkeypatch) -> None:
    monkeypatch.setattr(
        "edge.web.confirm_latest",
        lambda requested: (_ for _ in ()).throw(UpdateError("Versão inválida.")),
    )
    monkeypatch.setattr(
        "edge.web.release_status",
        lambda: ReleaseStatus(current="v1.0.1", latest="v1.0.2"),
    )
    listener = TrapListener(allowlist=Allowlist())
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(listener))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        request = Request(f"http://127.0.0.1:{port}/update", data=b"version=nope", method="POST")
        with urlopen(request, timeout=5) as response:
            html = response.read().decode("utf-8")
    finally:
        server.shutdown()
        server.server_close()
    assert "Versão inválida." in html
    assert 'id="open-update"' in html
    assert 'name="token"' in html
