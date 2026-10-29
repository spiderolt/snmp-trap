from __future__ import annotations

from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs

from edge.config import DEFAULT_PORT, EdgeConfig, save_config
from edge.listener import TrapListener

_STATIC = Path(__file__).resolve().parent / "static"
_ASSETS = {
    "/assets/logo.png": (_STATIC / "logo.png").read_bytes(),
    "/assets/logo-dark.png": (_STATIC / "logo-dark.png").read_bytes(),
}

_PAGE_STYLE = """
:root {
  color-scheme: light;
  --bg-canvas: #f3f5f7;
  --bg-elevated: #ffffff;
  --border: #e0e5ea;
  --border-strong: #b8c2cc;
  --text: #202a34;
  --text-muted: #687583;
  --text-inverse: #f4f8fb;
  --accent: #5b79c7;
  --accent-strong: #4563ad;
  --focus: #5b79c7;
  --online: #238756;
  --online-soft: #e7f5ed;
  --warning: #a65d00;
  --warning-soft: #fce8c7;
  --critical: #c75f6a;
  --critical-soft: #fbe9eb;
  --shadow: 0 1px 2px rgb(8 16 28 / 0.025);
  --font-sans: "IBM Plex Sans", "Segoe UI", sans-serif;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  min-height: 100vh;
  display: grid;
  place-items: center;
  padding: 1.5rem;
  background: var(--bg-canvas);
  color: var(--text);
  font-family: var(--font-sans);
  font-size: 0.9375rem;
  line-height: 1.45;
}
.panel {
  width: min(28rem, 100%);
  padding: 1.25rem;
  border: 1px solid var(--border);
  border-radius: 12px;
  background: var(--bg-elevated);
  box-shadow: var(--shadow);
}
.brand {
  display: flex;
  align-items: center;
  gap: 0.75rem;
}
.logo {
  width: 64px;
  height: 60px;
  object-fit: contain;
}
.logo-dark { display: none; }
.brand strong {
  display: block;
  font-size: 1.08rem;
  font-weight: 600;
  letter-spacing: -0.03em;
}
.brand strong span { color: var(--accent); }
.brand small {
  color: var(--text-muted);
  font-size: 0.75rem;
}
.lead, .hint, .note {
  margin: 0.75rem 0 0;
  color: var(--text-muted);
  font-size: 0.8125rem;
}
.stats {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 0.75rem;
  margin: 1rem 0 0;
}
.stats div {
  padding: 0.75rem;
  border-radius: 8px;
  background: color-mix(in srgb, var(--border) 45%, var(--bg-elevated));
}
.stats dt {
  color: var(--text-muted);
  font-size: 0.75rem;
  font-weight: 500;
}
.stats dd {
  margin: 0.15rem 0 0;
  font-size: 1.125rem;
  font-weight: 600;
}
.note {
  padding: 0.75rem;
  border-radius: 8px;
}
.note.ok { background: var(--online-soft); color: var(--online); }
.note.warn { background: var(--warning-soft); color: var(--warning); }
.note.alert { background: var(--critical-soft); color: var(--critical); }
form { display: grid; gap: 0.25rem; margin-top: 1rem; }
label {
  display: grid;
  gap: 0.25rem;
  margin-top: 0.75rem;
  color: var(--text-muted);
  font-size: 0.8125rem;
  font-weight: 500;
}
input {
  width: 100%;
  min-height: 44px;
  padding: 0 0.75rem;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--bg-elevated);
  color: var(--text);
  font: inherit;
  transition: border-color 160ms ease, box-shadow 160ms ease;
}
input:hover { border-color: var(--border-strong); }
input:focus {
  border-color: var(--focus);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--focus) 14%, transparent);
  outline: none;
}
button {
  margin-top: 1.25rem;
  min-height: 44px;
  border: 1px solid var(--accent-strong);
  border-radius: 8px;
  background: var(--accent-strong);
  color: var(--text-inverse);
  font: inherit;
  font-weight: 600;
  cursor: pointer;
}
button:hover { filter: brightness(0.96); }
@media (prefers-color-scheme: dark) {
  :root {
    color-scheme: dark;
    --bg-canvas: #111417;
    --bg-elevated: #1d2227;
    --border: #2b3239;
    --border-strong: #4d5862;
    --text: #edf1f5;
    --text-muted: #98a3ad;
    --text-inverse: #101820;
    --accent: #9bb5ee;
    --accent-strong: #7898df;
    --focus: #9bb5ee;
    --online: #72d5a2;
    --online-soft: #203a2e;
    --warning: #f0b429;
    --warning-soft: #3a2c10;
    --critical: #e9959e;
    --critical-soft: #41282f;
    --shadow: 0 1px 2px rgb(0 0 0 / 0.35);
  }
  .logo-light { display: none; }
  .logo-dark { display: block; }
}
"""


def make_handler(listener: TrapListener):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            path = self.path.split("?", 1)[0]
            asset = _ASSETS.get(path)
            if asset is not None:
                self._send(200, asset, "image/png")
                return
            if path == "/healthz":
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
    listening = stats.listening_port if stats.listening_port is not None else "fechada"
    notes: list[str] = []
    if stats.last_error:
        notes.append(f'<p class="note alert" role="alert">{escape(stats.last_error)}</p>')
    if message == "Configuração salva.":
        notes.append(f'<p class="note ok" role="status">{escape(message)}</p>')
    elif message:
        notes.append(f'<p class="note alert" role="alert">{escape(message)}</p>')
    if config.trap_port == 162:
        notes.append('<p class="note warn">A porta 162 costuma estar com o Zabbix.</p>')
    return f"""<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>SpiderOLT · Agente de traps</title>
  <style>{_PAGE_STYLE}</style>
</head>
<body>
  <main class="panel">
    <header class="brand">
      <img class="logo logo-light" src="/assets/logo.png" alt="" width="64" height="60">
      <img class="logo logo-dark" src="/assets/logo-dark.png" alt="" width="64" height="60">
      <div>
        <strong>Spider<span>OLT</span></strong>
        <small>Agente de traps</small>
      </div>
    </header>
    <p class="lead">A porta UDP padrão é {DEFAULT_PORT}.</p>
    <dl class="stats">
      <div><dt>Escutando</dt><dd>{escape(str(listening))}</dd></div>
      <div><dt>Recebidos</dt><dd>{stats.received}</dd></div>
      <div><dt>Enviados</dt><dd>{stats.sent}</dd></div>
    </dl>
    {"".join(notes)}
    <form method="post" action="/">
      <label>Porta UDP
        <input name="trap_port" type="number" min="1" max="65535" required value="{config.trap_port}">
      </label>
      <label>Endereço da API
        <input name="api_host" type="text" placeholder="site.spiderolt.com" autocomplete="off" value="{escape(config.api_host)}">
      </label>
      <label>Token
        <input name="token" type="password" autocomplete="off" value="{escape(config.token)}">
      </label>
      <button type="submit">Salvar</button>
    </form>
  </main>
</body>
</html>
"""


def serve_http(listener: TrapListener, port: int) -> None:
    server = ThreadingHTTPServer(("0.0.0.0", port), make_handler(listener))
    server.serve_forever()
