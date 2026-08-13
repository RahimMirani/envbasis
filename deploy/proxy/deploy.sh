#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

for required_file in .env proxy.env Caddyfile compose.yml; do
  if [[ ! -f "$required_file" ]]; then
    echo "Missing $SCRIPT_DIR/$required_file" >&2
    exit 1
  fi
done

chmod 600 .env proxy.env

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker is not installed. Run deploy/aws/bootstrap-amazon-linux.sh first." >&2
  exit 1
fi

docker compose config --quiet
docker compose build --pull proxy
docker compose up -d --remove-orphans

for attempt in {1..30}; do
  if docker compose exec -T proxy python -c \
    "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=3).read()" \
    >/dev/null 2>&1; then
    docker compose ps
    echo "Proxy deployment is ready."
    exit 0
  fi
  sleep 2
done

docker compose ps
docker compose logs --tail=100 proxy caddy
echo "Proxy did not become ready within 60 seconds." >&2
exit 1
