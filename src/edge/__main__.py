from __future__ import annotations

import threading

from edge.config import config_path, http_port, load_config, save_config
from edge.listener import TrapListener
from edge.web import serve_http
from trap_receiver.security import Allowlist


def main() -> None:
    config = load_config()
    if not config_path().exists():
        config = save_config(config)
    listener = TrapListener(allowlist=Allowlist())
    listener.set_config(config)
    try:
        listener.bind(config.trap_port)
    except OSError as exc:
        listener.stats.last_error = f"Não foi possível abrir a porta {config.trap_port}: {exc}"
    worker = threading.Thread(target=listener.serve_forever, name="trap-listener", daemon=True)
    worker.start()
    serve_http(listener, http_port())


if __name__ == "__main__":
    main()
