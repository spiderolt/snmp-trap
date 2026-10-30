from pathlib import Path

def test_install_removes_unused_images_after_the_update() -> None:
    script = Path(__file__).resolve().parents[1].joinpath("install.sh").read_text(encoding="utf-8")
    pull = script.index('docker compose --project-directory "${DEST}" pull')
    stop = script.index('docker compose --project-directory "${DEST}" stop')
    migrate = script.index('copy_config_from_volume "${volume}"')
    up = script.index('docker compose --project-directory "${DEST}" up -d')
    prune = script.index("docker image prune -af")
    assert pull < stop < migrate < up < prune
    assert "--volumes" not in script
    assert "snmp-trap-config:/var/lib/snmp-trap" not in script
    assert "- /var/lib/snmp-trap:/var/lib/snmp-trap" in script
    assert 'STATE_DIR="/var/lib/snmp-trap"' in script
