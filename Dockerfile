FROM python:3.12-slim AS production

WORKDIR /app
COPY src /app

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app
ENV SNMP_TRAP_CONFIG_PATH=/var/lib/snmp-trap/config.json
ENV SNMP_TRAP_HTTP_PORT=8088

CMD ["python", "-m", "edge"]
