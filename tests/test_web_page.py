from __future__ import annotations

import json
import socket
import threading
from datetime import datetime, timedelta, timezone
from http.server import ThreadingHTTPServer
from urllib.request import Request, urlopen

from edge.config import EdgeConfig
from edge.listener import EdgeStats, TrapListener
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
    assert 'action="/count"' in html
    assert "Iniciar contagem" in html
    assert 'action="/reload"' in html
    assert "Forçar reload" in html
    assert "para depois de um dia" in html
    assert "Nenhum trap desde que o agente subiu." in html


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
    assert "Recarregar" in html
    assert 'location.replace("/")' in html


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


def test_counter_starts_at_zero_and_resets_after_a_day() -> None:
    stats = EdgeStats()
    started = datetime(2026, 11, 2, 15, 0, tzinfo=timezone.utc)
    stats.record_received(started)
    stats.record_sent(started)
    assert stats.received == 0
    assert stats.sent == 0
    assert stats.last_received_at == started

    stats.start_counting(started)
    stats.record_received(started + timedelta(hours=1))
    stats.record_sent(started + timedelta(hours=1))
    assert stats.received == 1
    assert stats.sent == 1

    stats.record_received(started + timedelta(days=1))
    assert stats.counting is False
    assert stats.received == 0
    assert stats.sent == 0


def test_render_stops_a_count_after_one_day() -> None:
    listener = TrapListener(allowlist=Allowlist())
    listener.stats.start_counting(datetime.now(timezone.utc) - timedelta(days=1, seconds=1))
    listener.stats.received = 12
    listener.stats.sent = 3

    html = render(listener)

    assert listener.stats.counting is False
    assert "Iniciar contagem" in html
    assert "<dd>0</dd>" in html
    assert "Contando desde" not in html


def test_count_button_resets_and_starts(monkeypatch) -> None:
    monkeypatch.setattr("edge.web.release_status", lambda: ReleaseStatus(current="v1.0.4"))
    listener = TrapListener(allowlist=Allowlist())
    listener.stats.received = 40
    listener.stats.sent = 10
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(listener))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        request = Request(f"http://127.0.0.1:{port}/count", data=b"", method="POST")
        with urlopen(request, timeout=5) as response:
            html = response.read().decode("utf-8")
    finally:
        server.shutdown()
        server.server_close()
    assert listener.stats.counting is True
    assert listener.stats.received == 0
    assert "Contagem iniciada." in html
    assert "Reiniciar contagem" in html
    assert "Contando desde" in html


def test_reload_reopens_the_udp_port(monkeypatch) -> None:
    monkeypatch.setattr("edge.web.release_status", lambda: ReleaseStatus(current="v1.0.4"))
    listener = TrapListener(allowlist=Allowlist())
    listener.set_config(EdgeConfig(trap_port=1162))
    listener.stats.last_error = "Não foi possível abrir a porta 1162."
    opened: list[int] = []

    def bind(port: int) -> None:
        opened.append(port)
        listener.stats.listening_port = port

    listener.bind = bind  # type: ignore[method-assign]
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(listener))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        request = Request(f"http://127.0.0.1:{port}/reload", data=b"", method="POST")
        with urlopen(request, timeout=5) as response:
            html = response.read().decode("utf-8")
    finally:
        listener.stop()
        server.shutdown()
        server.server_close()
    assert opened == [1162]
    assert listener.stats.last_error == ""
    assert "Escuta recarregada." in html
    assert 'class="note ok"' in html


def test_a_bad_trap_does_not_stop_the_listener() -> None:
    listener = TrapListener(allowlist=Allowlist())

    class Sock:
        def __init__(self) -> None:
            self.calls = 0

        def recvfrom(self, _size: int) -> tuple[bytes, tuple[str, int]]:
            self.calls += 1
            if self.calls == 1:
                return b"trap", ("192.0.2.8", 161)
            listener.stop()
            raise socket.timeout()

        def close(self) -> None:
            return None

    listener._socket = Sock()  # type: ignore[assignment]

    def explode(_payload: bytes, _source: str) -> None:
        raise RuntimeError("quebrado")

    listener._handle = explode  # type: ignore[method-assign]
    listener.serve_forever()
    assert listener.stats.last_error == "Falha ao processar o trap."
