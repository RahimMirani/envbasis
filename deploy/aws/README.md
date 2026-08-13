# AWS resources for EnvBasis

These files support the low-cost two-instance deployment described in
[`deploy/README.md`](../README.md).

## `bootstrap-amazon-linux.sh`

Run this on each Amazon Linux 2023 EC2 instance after connecting with Systems
Manager Session Manager:

```bash
cd /opt/envbasis/repo
sudo bash deploy/aws/bootstrap-amazon-linux.sh
```

It installs Docker, Git, and the architecture-appropriate Docker Compose CLI
plugin, starts Docker, and creates `/opt/envbasis`. Start a new Session Manager
session afterward so the Docker group membership takes effect.

## `backend-kms-policy.json`

Replace `AWS_REGION`, `AWS_ACCOUNT_ID`, and `KMS_KEY_ID`, then add the policy as
an inline policy on the backend EC2 role. Attach the AWS-managed
`AmazonSSMManagedInstanceCore` policy to both EC2 roles separately.

Do not attach this KMS policy to the proxy role. The proxy must not be able to
unwrap EnvBasis project keys.
