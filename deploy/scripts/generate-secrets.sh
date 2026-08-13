#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
OUTPUT_FILE="${SCRIPT_DIR}/.env.generated"

if [[ -e "$OUTPUT_FILE" ]]; then
  echo "Refusing to overwrite $OUTPUT_FILE" >&2
  exit 1
fi

umask 077

fernet_key() {
  openssl rand -base64 32 | tr '+/' '-_' | tr -d '\n'
}

long_secret() {
  openssl rand -base64 48 | tr -d '\n'
}

cat >"$OUTPUT_FILE" <<EOF
# Generated independently. Copy each value into the indicated private env file.
# Delete this file after storing the values in your password manager.

# deploy/backend/.env
REDIS_PASSWORD=$(openssl rand -hex 32)

# deploy/backend/backend.env
SECRETS_MASTER_KEY=$(fernet_key)
API_IDEMPOTENCY_ENCRYPTION_KEY=$(fernet_key)
CLI_AUTH_JWT_SECRET=$(long_secret)
MACHINE_AUTH_JWT_SECRET=$(long_secret)
EOF

chmod 600 "$OUTPUT_FILE"
echo "Generated secrets in $OUTPUT_FILE (mode 600)."
echo "Copy them into the private deployment env files, store an offline backup, then delete the generated file."
