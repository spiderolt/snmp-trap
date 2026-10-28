from __future__ import annotations

from edge.config import EdgeConfig
from edge.listener import TrapListener
from edge.web import render
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
    assert 'value="site.spiderolt.com"' in html
    assert "Configuração salva." in html
    assert 'class="note ok"' in html
