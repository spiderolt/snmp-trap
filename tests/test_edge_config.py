from __future__ import annotations

import json

import pytest

from edge.config import DEFAULT_ALLOWLIST, EdgeConfig, config_path, load_config, normalize_allowlist, save_config
from edge.listener import TrapListener
from edge.url import ingest_url
from trap_receiver.security import Allowlist, parse_allowlist


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


def test_allowlist_accepts_a_host_and_rejects_text() -> None:
    assert parse_allowlist("10.0.0.0/8\n45.7.152.13\n10.0.0.0/8") == ["10.0.0.0/8", "45.7.152.13/32"]
    with pytest.raises(ValueError, match="Rede inválida"):
        parse_allowlist("olt")
    with pytest.raises(ValueError, match="ao menos uma rede"):
        normalize_allowlist("  \n")


def test_missing_allowlist_keeps_private_ranges_or_the_environment(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "config.json"
    target.write_text('{"trap_port": 1162, "api_host": "site.spiderolt.com", "token": "edge_abc"}', encoding="utf-8")
    monkeypatch.setenv("SNMP_TRAP_CONFIG_PATH", str(target))
    monkeypatch.delenv("TRAP_ALLOWLIST_CIDRS", raising=False)
    assert "10.0.0.0/8" in load_config().allowlist

    monkeypatch.setenv("TRAP_ALLOWLIST_CIDRS", "192.0.2.0/24")
    loaded = load_config()
    assert loaded.allowlist == "192.0.2.0/24"
    assert DEFAULT_ALLOWLIST.startswith("10.0.0.0/8")


def test_saved_allowlist_filters_the_next_trap(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "config.json"
    monkeypatch.setenv("SNMP_TRAP_CONFIG_PATH", str(target))
    config = EdgeConfig(allowlist=normalize_allowlist("10.0.0.0/8\n192.0.2.8"))
    save_config(config)
    listener = TrapListener(allowlist=Allowlist())
    listener.set_config(load_config())
    assert listener.allowlist.allows("192.0.2.8")
    assert not listener.allowlist.allows("198.51.100.10")


def test_blank_credentials_keep_the_saved_ones(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "config.json"
    monkeypatch.setenv("SNMP_TRAP_CONFIG_PATH", str(target))
    save_config(EdgeConfig(trap_port=1162, api_host="site.spiderolt.com", token="edge_abc"))
    loaded = save_config(EdgeConfig(trap_port=162, api_host="", token=""))
    assert loaded.api_host == "site.spiderolt.com"
    assert loaded.token == "edge_abc"
    assert loaded.trap_port == 162
    assert load_config().token == "edge_abc"


def test_new_credentials_replace_the_saved_ones(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "config.json"
    monkeypatch.setenv("SNMP_TRAP_CONFIG_PATH", str(target))
    save_config(EdgeConfig(api_host="site.spiderolt.com", token="edge_abc"))
    loaded = save_config(EdgeConfig(api_host="outro.spiderolt.com", token="edge_new"))
    assert loaded.api_host == "outro.spiderolt.com"
    assert loaded.token == "edge_new"


def test_invalid_port_falls_back(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "config.json"
    target.write_text('{"trap_port": 0, "api_host": "", "token": ""}', encoding="utf-8")
    monkeypatch.setenv("SNMP_TRAP_CONFIG_PATH", str(target))
    assert load_config().trap_port == 1162
