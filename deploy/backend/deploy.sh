#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

for required_file in .env backend.env Caddyfile compose.yml; do
  if [[ ! -f "$required_file" ]]; then
    echo "Missing $SCRIPT_DIR/$required_file" >&2
    exit 1
  fi
done

chmod 600 .env backend.env

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker is not installed. Run deploy/aws/bootstrap-amazon-linux.sh first." >&2
  exit 1
fi

docker compose config --quiet
docker compose build --pull backend
docker compose up -d redis
docker compose run --rm --no-deps backend alembic upgrade head

if [[ "${1:-}" == "--with-webhooks" ]]; then
  docker compose --profile webhooks up -d --remove-orphans
else
  docker compose up -d --remove-orphans
fi

for attempt in {1..30}; do
  if docker compose exec -T backend python -c \
    "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/ready', timeout=3).read()" \
    >/dev/null 2>&1; then
    docker compose ps
    echo "Backend deployment is ready."
    exit 0
  fi
  sleep 2
done

docker compose ps
docker compose logs --tail=100 backend redis caddy
echo "Backend did not become ready within 60 seconds." >&2
exit 1
