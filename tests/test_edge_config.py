from __future__ import annotations

import json

import pytest

from edge.config import EdgeConfig, config_path, load_config, save_config
from edge.url import ingest_url


def test_ingest_url_keeps_only_the_host() -> None:
    assert ingest_url("site.spiderolt.com") == "https://site.spiderolt.com/api/snmp-trap/traps"
    assert ingest_url("https://site.spiderolt.com/qualquer/caminho") == "https://site.spiderolt.com/api/snmp-trap/traps"
    assert ingest_url("http://localhost:8000/api") == "http://localhost:8000/api/snmp-trap/traps"


def test_ingest_url_rejects_an_empty_host() -> None:
    with pytest.raises(ValueError):
        ingest_url("   ")


def test_config_roundtrip(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "config.json"
    monkeypatch.setenv("SNMP_TRAP_CONFIG_PATH", str(target))
    save_config(EdgeConfig(trap_port=1162, api_host="site.spiderolt.com", token="edge_abc"))
    loaded = load_config()
    assert loaded.trap_port == 1162
    assert loaded.api_host == "site.spiderolt.com"
    assert loaded.token == "edge_abc"
    assert json.loads(config_path().read_text(encoding="utf-8"))["trap_port"] == 1162


def test_invalid_port_falls_back(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "config.json"
    target.write_text('{"trap_port": 0, "api_host": "", "token": ""}', encoding="utf-8")
    monkeypatch.setenv("SNMP_TRAP_CONFIG_PATH", str(target))
    assert load_config().trap_port == 1162
