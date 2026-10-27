from __future__ import annotations

from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs

from edge.config import DEFAULT_PORT, EdgeConfig, save_config
from edge.listener import TrapListener


def make_handler(listener: TrapListener):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            if self.path.split("?", 1)[0] == "/healthz":
                port = listener.stats.listening_port
                body = f"ok port={port}\n".encode("utf-8")
                self._send(200, body, "text/plain; charset=utf-8")
                return
            self._send(200, render(listener).encode("utf-8"), "text/html; charset=utf-8")

        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("Content-Length", "0") or "0")
            raw = self.rfile.read(length).decode("utf-8", errors="replace")
            form = parse_qs(raw, keep_blank_values=True)
            current = listener.current_config()
            message = ""
            try:
                port = int((form.get("trap_port") or [str(current.trap_port)])[0])
            except ValueError:
                port = 0
            if not 1 <= port <= 65535:
                message = "A porta precisa estar entre 1 e 65535."
                port = current.trap_port
            proposed = EdgeConfig(
                trap_port=port,
                api_host=(form.get("api_host") or [""])[0].strip(),
                token=(form.get("token") or [""])[0].strip(),
            )
            if message == "" and proposed.trap_port != listener.stats.listening_port:
                try:
                    listener.bind(proposed.trap_port)
                except OSError:
                    message = f"Não foi possível abrir a porta {proposed.trap_port}."
                    proposed.trap_port = current.trap_port
            if message == "":
                message = "Configuração salva."
            listener.set_config(proposed)
            save_config(proposed)
            body = render(listener, message=message).encode("utf-8")
            self._send(200, body, "text/html; charset=utf-8")

        def log_message(self, format: str, *args) -> None:  # noqa: A003
            return

        def _send(self, status: int, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return Handler


def render(listener: TrapListener, *, message: str = "") -> str:
    config = listener.current_config()
    stats = listener.stats
    port_note = ""
    if config.trap_port == 162:
        port_note = "<p>A porta 162 costuma estar com o Zabbix.</p>"
    error = f"<p>{escape(stats.last_error)}</p>" if stats.last_error else ""
    notice = f"<p>{escape(message)}</p>" if message else ""
    listening = stats.listening_port if stats.listening_port is not None else "fechada"
    return f"""<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Agente de traps</title>
  <style>
    body {{ font-family: sans-serif; margin: 2rem auto; max-width: 36rem; line-height: 1.4; }}
    label {{ display: block; margin-top: 1rem; }}
    input {{ width: 100%; box-sizing: border-box; margin-top: 0.25rem; }}
    button {{ margin-top: 1rem; }}
  </style>
</head>
<body>
  <h1>Agente de traps</h1>
  <p>A porta UDP padrão é {DEFAULT_PORT}. O Zabbix continua na 162.</p>
  <p>Escutando na porta {escape(str(listening))}. Recebidos: {stats.received}. Enviados: {stats.sent}.</p>
  {error}
  {notice}
  <form method="post" action="/">
    <label>Porta UDP
      <input name="trap_port" type="number" min="1" max="65535" required value="{config.trap_port}">
    </label>
    {port_note}
    <label>Endereço da API
      <input name="api_host" type="text" placeholder="site.spiderolt.com" value="{escape(config.api_host)}">
    </label>
    <p>O caminho /api/snmp-trap/traps é acrescentado ao endereço. Um caminho colado aqui é ignorado.</p>
    <label>Token
      <input name="token" type="password" autocomplete="off" value="{escape(config.token)}">
    </label>
    <button type="submit">Salvar</button>
  </form>
</body>
</html>
"""


def serve_http(listener: TrapListener, port: int) -> None:
    server = ThreadingHTTPServer(("0.0.0.0", port), make_handler(listener))
    server.serve_forever()
