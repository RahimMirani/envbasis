# Deploy EnvBasis backend and agent proxy on AWS

This directory contains a low-cost production-MVP deployment for EnvBasis. It
uses two Amazon Linux 2023 EC2 instances so the agent-facing proxy is isolated
from the backend's database access, root encryption key, and KMS permission.

```text
api.example.com                         proxy.example.com
        |                                       |
      Caddy                                   Caddy
        |                                       |
  FastAPI backend                         Agent proxy
     |       |                              |       |
   Redis  AWS KMS                         OpenAI  GitHub
     |
Supabase Postgres/Auth
```

This layout deliberately avoids an Application Load Balancer, NAT Gateway, ECS,
and managed Redis. It is inexpensive and easy to operate, but each service has a
single-instance availability boundary. Move to multi-AZ ECS/RDS/ElastiCache when
the traffic or uptime requirement justifies that cost.

## Files

| Path | Purpose |
| --- | --- |
| `backend/compose.yml` | Backend API, private Redis, optional webhook worker, and Caddy |
| `backend/backend.env.example` | Backend production environment template |
| `backend/.env.example` | Backend Compose domain and Redis password template |
| `backend/deploy.sh` | Build, migrate, deploy, and readiness check |
| `proxy/compose.yml` | Proxy and Caddy |
| `proxy/proxy.env.example` | Proxy production environment template |
| `proxy/.env.example` | Proxy Compose domain template |
| `proxy/deploy.sh` | Build, deploy, and health check |
| `aws/bootstrap-amazon-linux.sh` | Docker/Compose bootstrap for Amazon Linux 2023 |
| `aws/backend-kms-policy.json` | Least-privilege backend KMS policy template |
| `scripts/generate-secrets.sh` | Generates independent production secrets locally |

## 1. Before creating AWS resources

1. Commit and push the exact release you intend to deploy. Do not deploy an
   uncommitted workstation tree.
2. Run the backend and proxy test suites.
3. Own a domain and choose two names, for example:
   - `api.example.com`
   - `proxy.example.com`
4. Know the deployed frontend origin, for example `https://app.example.com`.
5. Choose the AWS region nearest the Supabase project. The examples use
   `us-west-2`; replace it everywhere if you choose another region.
6. In AWS Billing, create a monthly budget with email alerts at 50%, 80%, and
   100%. Also check the credit expiration date.

Run tests from the repository root:

```bash
cd console/backend
python -m pytest -q

cd ../../proxy
PYTHONPATH=src python -m pytest -q
```

## 2. Generate application secrets

Run this on your trusted workstation, not on EC2:

```bash
bash deploy/scripts/generate-secrets.sh
```

The script creates `deploy/scripts/.env.generated` with mode `600`. Copy each
value to the indicated private environment file and your password manager. The
keys are independent by design; do not reuse one value for multiple settings.
Delete `.env.generated` after the values are safely stored.

The `MACHINE_AUTH_JWT_SECRET` is the one intentional cross-host value: copy that
exact value to the backend and proxy configurations. The proxy uses it to verify
short-lived machine tokens issued by the backend.

## 3. Get the Supabase values

Collect:

- Project URL
- JWT secret (for the current `HS256` configuration)
- Database password
- Session Pooler connection string

In Supabase, open the project and click **Connect**. For an IPv4 EC2 host, select
the **Session Pooler** connection on port `5432`. Convert its scheme for this
application:

```text
postgres://...
```

becomes:

```text
postgresql+psycopg://...
```

Keep `?sslmode=require`. URL-encode special characters in the database password.
The session pooler is preferable here because Supabase's normal direct database
hostname is IPv6 unless the project has the IPv4 add-on.

After the backend Elastic IP exists, restrict Supabase database ingress to that
address as a `/32` if the project's network-restriction controls are available.

## 4. Create the KMS key

In AWS KMS, in the chosen region:

1. Open **Customer managed keys** and choose **Create key**.
2. Choose **Symmetric** and **Encrypt and decrypt**.
3. Set alias `alias/envbasis`.
4. Select your administrator identity as the key administrator.
5. Finish creation and copy the key ARN.

Do not enable automatic key rotation merely to rotate EnvBasis project data
keys. AWS KMS key-material rotation and the EnvBasis project-encryption rotation
endpoint solve different problems.

Never delete this KMS key while it protects EnvBasis data. Losing it makes
KMS-wrapped project keys unreadable.

## 5. Create the EC2 roles

Create `EnvBasisBackendInstanceRole` with EC2 as the trusted service:

1. Attach the AWS-managed `AmazonSSMManagedInstanceCore` policy.
2. Copy `deploy/aws/backend-kms-policy.json` into an inline policy.
3. Replace `AWS_REGION`, `AWS_ACCOUNT_ID`, and `KMS_KEY_ID` with the real values.

Create `EnvBasisProxyInstanceRole` with EC2 as the trusted service:

1. Attach only `AmazonSSMManagedInstanceCore`.
2. Do not grant database, KMS, or backend-secret access.

The backend policy permits only `kms:GenerateDataKey` and `kms:Decrypt` on one
specific key and only with EnvBasis's encryption-purpose context.

## 6. Create security groups

Create `envbasis-backend-sg` and `envbasis-proxy-sg` with the same public rules:

| Type | Port | Source |
| --- | ---: | --- |
| HTTP | 80 | `0.0.0.0/0` and `::/0` if IPv6 is enabled |
| HTTPS | 443 | `0.0.0.0/0` and `::/0` if IPv6 is enabled |

Keep the default outbound access. Do not add inbound rules for SSH `22`, backend
`8000`, proxy `8080`, or Redis `6379`. Administration uses Session Manager.

## 7. Launch the EC2 instances

Launch the backend instance:

- Latest Amazon Linux 2023 ARM64 AMI
- `t4g.small`
- 20 GiB encrypted gp3 root volume
- `EnvBasisBackendInstanceRole`
- `envbasis-backend-sg`
- Public subnet with a public IPv4 address
- IMDSv2 required
- Metadata response hop limit `2`
- Detailed monitoring optional
- Termination protection enabled

Launch the proxy instance:

- Latest Amazon Linux 2023 ARM64 AMI
- `t4g.micro` initially; use `t4g.small` if streams are concurrent
- 16 GiB encrypted gp3 root volume
- `EnvBasisProxyInstanceRole`
- `envbasis-proxy-sg`
- Public subnet with a public IPv4 address
- IMDSv2 required
- Termination protection enabled

The backend metadata hop limit must be `2` so the container can obtain temporary
instance-role credentials for KMS. Never put static AWS access keys in
`backend.env`.

Allocate and associate one Elastic IP with each instance. Record both addresses.
An Elastic IP keeps DNS stable across stop/start operations, but it is billed
whether attached or idle, so release it when permanently deleting the stack.

## 8. Configure DNS

At Route 53 or the existing DNS provider, create:

```text
api.example.com    A    BACKEND_ELASTIC_IP
proxy.example.com  A    PROXY_ELASTIC_IP
```

Wait until both names resolve publicly. Caddy cannot obtain TLS certificates
until DNS is correct and inbound ports 80 and 443 are reachable.

## 9. Put the repository on each instance

Connect through **EC2 → Instance → Connect → Session Manager**. No SSH key is
needed.

On each instance, install Git, create the application directory, and clone the
committed release:

```bash
sudo dnf install -y git
sudo install -d -o "$USER" -g "$USER" -m 0755 /opt/envbasis
git clone https://github.com/RahimMirani/envbasis.git /opt/envbasis/repo
cd /opt/envbasis/repo
git switch --detach YOUR_TESTED_COMMIT_OR_TAG
sudo bash deploy/aws/bootstrap-amazon-linux.sh
```

For a private repository, use a read-only GitHub deploy key or copy a release
archive onto the instance. Do not place a personal GitHub token in a command or
committed remote URL.

End the Session Manager session and open a new one so Docker group membership is
active. Confirm:

```bash
docker version
docker compose version
```

## 10. Configure and deploy the backend

On the backend instance:

```bash
cd /opt/envbasis/repo/deploy/backend
cp .env.example .env
cp backend.env.example backend.env
chmod 600 .env backend.env
```

Edit `.env`:

```dotenv
API_DOMAIN=api.example.com
REDIS_PASSWORD=the-generated-hex-value
```

Edit `backend.env` and replace every placeholder. Important values are:

- Supabase Session Pooler `DATABASE_URL`
- Supabase URL and JWT secret
- Both generated Fernet keys
- Both generated JWT secrets
- KMS key ARN and region
- Exact frontend origin for CORS and invitation links

Keep these settings:

```dotenv
APP_ENV=production
ENVBASIS_DEBUG=false
SECRETS_ROOT_KEY_PROVIDER=aws_kms
RATE_LIMIT_BACKEND=redis
WEBHOOKS_ENABLED=false
```

Deploy:

```bash
./deploy.sh
```

The script validates Compose, builds the image, starts Redis, runs
`alembic upgrade head`, starts the services, and waits for backend readiness.
It exits nonzero and prints recent logs if readiness fails.

To enable webhooks later, first change `WEBHOOKS_ENABLED=true`, then deploy the
separate worker profile:

```bash
./deploy.sh --with-webhooks
```

Do not enable the API feature without its worker.

## 11. Configure and deploy the proxy

On the proxy instance:

```bash
cd /opt/envbasis/repo/deploy/proxy
cp .env.example .env
cp proxy.env.example proxy.env
chmod 600 .env proxy.env
```

Edit `.env` with `proxy.example.com`. Edit `proxy.env` and:

1. Copy the backend's exact `MACHINE_AUTH_JWT_SECRET`.
2. Keep algorithm, issuer, and audience identical to the backend.
3. Set at least one of `OPENAI_API_KEY` or `GITHUB_TOKEN`.

The provider keys must exist only on this proxy instance. Deploy:

```bash
./deploy.sh
```

## 12. Verify the public services

From your workstation:

```bash
curl --fail --show-error https://api.example.com/api/v1/health
curl --fail --show-error https://api.example.com/api/v1/live
curl --fail --show-error https://api.example.com/api/v1/ready
curl --fail --show-error https://proxy.example.com/health
```

The backend readiness response must show both `database` and `rate_limiter` as
`true`. The backend Caddy configuration intentionally returns `404` for the
public `/api/v1/metrics` endpoint.

Verify the certificate issuer and expiration:

```bash
openssl s_client -connect api.example.com:443 -servername api.example.com </dev/null 2>/dev/null \
  | openssl x509 -noout -issuer -subject -dates
```

Then test the complete product flow:

1. Configure the frontend with
   `VITE_API_BASE_URL=https://api.example.com/api/v1` and rebuild it.
2. Add `https://app.example.com/auth/callback` to Supabase OAuth redirects.
3. Sign in and create a project and environment.
4. Create, reveal, update, and delete a disposable secret.
5. Create a machine identity and copy its client ID/secret once.
6. Exchange the credential at the backend for a short-lived access token.
7. Call the proxy with that access token.

Example token exchange:

```bash
curl --fail --show-error \
  -X POST https://api.example.com/api/v1/machine-identities/token \
  -H 'Content-Type: application/json' \
  --data '{"client_id":"YOUR_CLIENT_ID","client_secret":"YOUR_CLIENT_SECRET"}'
```

Example proxy health and OpenAI-model request:

```bash
curl --fail --show-error https://proxy.example.com/health
curl --fail --show-error https://proxy.example.com/openai/v1/models \
  -H "Authorization: Bearer YOUR_SHORT_LIVED_MACHINE_TOKEN"
```

## 13. Existing encrypted data and KMS migration

`SECRETS_MASTER_KEY` remains required even with `SECRETS_ROOT_KEY_PROVIDER=aws_kms`:

- Startup currently validates it.
- Legacy secret ciphertext may use it directly.
- Project keys created under the local provider still require it for unwrapping.

Back up this key offline. Switching the active provider to KMS affects new
project keys; it does not magically rewrite existing local-wrapped project keys.
After backing up the database and root key, rotate each existing project through
the project encryption-rotation API to migrate its active ciphertext to a newly
KMS-wrapped project key. Verify the result before ever considering retirement of
the local key. In practice, retain the local key as recovery material.

## 14. Routine operations

View status and logs:

```bash
cd /opt/envbasis/repo/deploy/backend
docker compose ps
docker compose logs --tail=200 backend redis caddy

cd /opt/envbasis/repo/deploy/proxy
docker compose ps
docker compose logs --tail=200 proxy caddy
```

Deploy a tested update on each host:

```bash
cd /opt/envbasis/repo
git fetch --tags origin
git switch --detach YOUR_NEW_TESTED_TAG_OR_COMMIT

cd deploy/backend  # or deploy/proxy on the proxy host
./deploy.sh
```

The Compose services use `restart: unless-stopped`, so they return after an EC2
reboot when Docker starts.

For a code rollback, switch back to the previous tested commit and run the
deployment script. Database migrations are a separate compatibility concern:
take a Supabase backup before migration and do not run blind Alembic downgrades.

## 15. Hardening before meaningful production traffic

- Move the private environment values to SSM Parameter Store or Secrets Manager
  and materialize them at deployment time using narrowly scoped instance roles.
- Configure CloudWatch alarms for EC2 CPU, status checks, disk usage, and budget.
- Enable automated Supabase backups appropriate to the data's sensitivity.
- Restrict Supabase database networking to the backend Elastic IP.
- Keep Amazon Linux, Docker, images, and Python dependencies patched.
- Rotate provider credentials and machine credentials on a schedule.
- Keep proxy and backend roles separate.
- Never expose ports 22, 8000, 8080, or 6379.
- Treat EC2 snapshots and Supabase backups as sensitive encrypted material.
- Test restore procedures, not just backup creation.

## Troubleshooting

### Backend reports database not ready

- Confirm the Session Pooler host and port `5432` are used.
- Confirm the scheme is `postgresql+psycopg://`.
- URL-encode the password.
- Confirm `sslmode=require` is present.
- If Supabase network restrictions are enabled, allow the backend Elastic IP.

### Backend cannot call KMS

- Confirm the backend instance has the backend role, not the proxy role.
- Confirm the KMS ARN and region in `backend.env`.
- Confirm IMDSv2 metadata hop limit is `2`.
- Confirm the inline policy placeholders were replaced.
- Inspect CloudTrail for denied `GenerateDataKey` or `Decrypt` calls.

### Caddy does not issue a certificate

- Confirm DNS resolves to the correct Elastic IP.
- Confirm security-group ports 80 and 443 are open.
- Confirm no other process owns those ports.
- Inspect `docker compose logs caddy`.

### Backend starts but most requests return 503

Production rate limiting fails closed when Redis is unavailable. Check:

```bash
docker compose ps redis
docker compose logs --tail=100 redis backend
```

Ensure `REDIS_PASSWORD` is a generated hex value and redeploy after correcting it.
