#!/usr/bin/env bash
set -euo pipefail

# Stamped by the release workflow. Empty resolves the latest GitHub release.
SNMP_TRAP_VERSION="${SNMP_TRAP_VERSION:-__SNMP_TRAP_VERSION__}"
SNMP_TRAP_REPO="${SNMP_TRAP_REPO:-spiderolt/snmp-trap}"
DEST="${SNMP_TRAP_DIR:-/opt/snmp-trap}"
HTTP_PORT=8088
TRAP_PORT=1162

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Execute como root: sudo bash install.sh"
  exit 1
fi

if [[ -z "${SNMP_TRAP_VERSION}" || "${SNMP_TRAP_VERSION}" == "__SNMP_TRAP_VERSION__" ]]; then
  SNMP_TRAP_VERSION="$(
    curl -fsSL -H "Accept: application/vnd.github+json" \
      "https://api.github.com/repos/${SNMP_TRAP_REPO}/releases/latest" \
      | awk -F'"' '/"tag_name"/ { print $4; exit }'
  )"
fi

if [[ -z "${SNMP_TRAP_VERSION}" ]]; then
  echo "Não foi possível ler o release mais recente de ${SNMP_TRAP_REPO}." >&2
  exit 1
fi

owner="$(printf '%s' "${SNMP_TRAP_REPO%%/*}" | tr '[:upper:]' '[:lower:]')"
IMAGE="${SNMP_TRAP_IMAGE:-ghcr.io/${owner}/snmp-trap:${SNMP_TRAP_VERSION}}"

if ! command -v docker >/dev/null 2>&1; then
  curl -fsSL https://get.docker.com | sh
fi

if ! docker compose version >/dev/null 2>&1; then
  echo "O plugin Docker Compose não está disponível."
  exit 1
fi

STATE_DIR="/var/lib/snmp-trap"
mkdir -p "${DEST}" "${STATE_DIR}"

cat > "${DEST}/docker-compose.yml" <<EOF
name: snmp-trap

services:
  snmp-trap:
    image: \${SNMP_TRAP_IMAGE}
    network_mode: host
    restart: unless-stopped
    environment:
      SNMP_TRAP_CONFIG_PATH: /var/lib/snmp-trap/config.json
      SNMP_TRAP_HTTP_PORT: "${HTTP_PORT}"
      TRAP_ALLOWLIST_CIDRS: \${TRAP_ALLOWLIST_CIDRS:-10.0.0.0/8,172.16.0.0/12,192.168.0.0/16}
    volumes:
      - /var/lib/snmp-trap:/var/lib/snmp-trap
EOF

cat > "${DEST}/.env" <<EOF
SNMP_TRAP_IMAGE=${IMAGE}
EOF

host_has_credentials() {
  [[ -f "${STATE_DIR}/config.json" ]] || return 1
  grep -Eq '"(api_host|token)"[[:space:]]*:[[:space:]]*"[^"]+' "${STATE_DIR}/config.json"
}

copy_config_from_volume() {
  local volume="$1"
  docker volume inspect "${volume}" >/dev/null 2>&1 || return 1
  docker run --rm --entrypoint python \
    -v "${volume}:/old:ro" \
    -v "${STATE_DIR}:/state" \
    "${IMAGE}" \
    -c 'import json
from pathlib import Path
src = Path("/old/config.json")
if not src.is_file():
    raise SystemExit(1)
raw = json.loads(src.read_text(encoding="utf-8"))
if not str(raw.get("api_host") or "").strip() and not str(raw.get("token") or "").strip():
    raise SystemExit(1)
Path("/state/config.json").write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
'
}

docker compose --project-directory "${DEST}" pull
if ! host_has_credentials; then
  docker compose --project-directory "${DEST}" stop || true
  volumes="$(docker volume ls -q --filter label=com.docker.compose.volume=snmp-trap-config || true)"
  if [[ -z "${volumes}" ]]; then
    volumes=$'snmp-trap_snmp-trap-config\nsnmp-trap-config'
  fi
  while IFS= read -r volume; do
    [[ -n "${volume}" ]] || continue
    if copy_config_from_volume "${volume}"; then
      break
    fi
  done <<< "${volumes}"
fi
chmod 700 "${STATE_DIR}"
if [[ -f "${STATE_DIR}/config.json" ]]; then
  chmod 600 "${STATE_DIR}/config.json"
fi

docker compose --project-directory "${DEST}" up -d
if ! docker image prune -af; then
  echo "limpeza de imagens antigas falhou" >&2
fi

IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
IP="${IP:-o IP deste servidor}"

cat <<EOF

Agente no ar (${SNMP_TRAP_VERSION}).
Imagem: ${IMAGE}
Tela: http://${IP}:${HTTP_PORT}

Informe o endereço da API, por exemplo site.spiderolt.com, e o token gerado no SpiderOLT.
Os dois ficam em /var/lib/snmp-trap/config.json e continuam neste servidor quando o agente reinicia ou atualiza.
A porta UDP já vem em ${TRAP_PORT}. Se mudar na tela, use a nova porta no comando da OLT.

Na OLT, em config, sem apagar os destinos que já existem:

snmp-agent target-host trap-paramsname spiderolt v2c securityname <COMMUNITY>
snmp-agent target-host trap-hostname spiderolt address ${IP} udp-port ${TRAP_PORT} trap-paramsname spiderolt
snmp-agent trap enable standard
save

EOF
