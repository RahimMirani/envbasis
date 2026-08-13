#!/usr/bin/env bash
set -Eeuo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run this script with sudo." >&2
  exit 1
fi

TARGET_USER="${SUDO_USER:-ec2-user}"

dnf update -y
dnf install -y docker git curl
systemctl enable --now docker

case "$(uname -m)" in
  aarch64 | arm64)
    COMPOSE_ARCH="aarch64"
    ;;
  x86_64 | amd64)
    COMPOSE_ARCH="x86_64"
    ;;
  *)
    echo "Unsupported CPU architecture: $(uname -m)" >&2
    exit 1
    ;;
esac

install -d -m 0755 /usr/local/lib/docker/cli-plugins
curl --fail --show-error --location \
  "https://github.com/docker/compose/releases/latest/download/docker-compose-linux-${COMPOSE_ARCH}" \
  --output /usr/local/lib/docker/cli-plugins/docker-compose
chmod 0755 /usr/local/lib/docker/cli-plugins/docker-compose

if id "$TARGET_USER" >/dev/null 2>&1; then
  usermod -aG docker "$TARGET_USER"
fi

install -d -o "$TARGET_USER" -g "$TARGET_USER" -m 0755 /opt/envbasis

docker version
docker compose version

echo
echo "Bootstrap complete. Start a new Session Manager session before using Docker without sudo."
