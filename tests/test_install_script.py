from pathlib import Path

def test_install_removes_unused_images_after_the_update() -> None:
    script = Path(__file__).resolve().parents[1].joinpath("install.sh").read_text(encoding="utf-8")
    pull = script.index('docker compose --project-directory "${DEST}" pull')
    up = script.index('docker compose --project-directory "${DEST}" up -d')
    prune = script.index("docker image prune -af")
    assert pull < up < prune
    assert "--volumes" not in script
