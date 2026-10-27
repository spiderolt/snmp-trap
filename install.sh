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

mkdir -p "${DEST}"

cat > "${DEST}/docker-compose.yml" <<EOF
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
      - snmp-trap-config:/var/lib/snmp-trap

volumes:
  snmp-trap-config:
EOF

cat > "${DEST}/.env" <<EOF
SNMP_TRAP_IMAGE=${IMAGE}
EOF

docker compose --project-directory "${DEST}" pull
docker compose --project-directory "${DEST}" up -d

IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
IP="${IP:-o IP deste servidor}"

cat <<EOF

Agente no ar (${SNMP_TRAP_VERSION}).
Imagem: ${IMAGE}
Tela: http://${IP}:${HTTP_PORT}

Informe o endereço da API, por exemplo site.spiderolt.com, e o token gerado no SpiderOLT.
A porta UDP já vem em ${TRAP_PORT}. Se mudar na tela, use a nova porta no comando da OLT.

Na OLT, em config, sem apagar os destinos que já existem:

snmp-agent target-host trap-paramsname spiderolt v2c securityname <COMMUNITY>
snmp-agent target-host trap-hostname spiderolt address ${IP} udp-port ${TRAP_PORT} trap-paramsname spiderolt
snmp-agent trap enable standard
save

EOF
