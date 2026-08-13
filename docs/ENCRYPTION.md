# EnvBasis Encryption Model

EnvBasis uses envelope encryption for project secrets.

```text
SECRETS_MASTER_KEY (root key)
        |
        | wraps and unwraps
        v
Per-project data-encryption key (DEK)
        |
        | encrypts and decrypts
        v
Secret values and their historical versions
```

## Stored data

The root key remains in application configuration and is never stored in the database.

For each project and key version, `project_encryption_keys` stores only:

- Project ID
- Key version
- Wrapped DEK ciphertext
- Active/retired state and timestamps

Each secret version stores its ciphertext and `encryption_key_version`. The plaintext DEK exists only temporarily in application memory while performing a cryptographic operation.

## New projects and writes

Creating a project provisions key version 1. The service also provisions a key lazily for projects created outside the API or before this feature.

Every new secret version is encrypted with the active project DEK and records that DEK's version. Project-key creation and secret writes lock the project row so they cannot race with rotation.

## Existing secrets

Secrets created before envelope encryption have `encryption_key_version = NULL`. They remain readable using the legacy root-key encryption path during rollout.

Calling the project rotation endpoint migrates every legacy secret version to the project's first DEK. This allows schema deployment and data migration to be separated safely.

## Rotation

Only the project owner may call:

```text
POST /api/v1/projects/{project_id}/encryption/rotate
```

Rotation performs one database transaction:

1. Lock the project against concurrent secret writes and other rotations.
2. Generate the next DEK version.
3. Wrap the new DEK with the root key.
4. Decrypt every secret version with its recorded key version.
5. Re-encrypt every secret version with the new DEK.
6. Persist the new key version on every secret.
7. Retire the previous project key.
8. Activate the new project key.
9. Write an audit event and commit once.

If any secret cannot be decrypted or any database operation fails, the transaction is rolled back. The previous key remains active and no partially migrated secret is committed.

Retired wrapped keys are retained so historical or interrupted operational recovery remains possible. No active secret should reference a retired key after successful rotation.

## Deployment procedure

1. Back up the database and confirm the root key is recoverable.
2. Apply Alembic migration `20260807_0010`.
3. Deploy the application, which can read both legacy and versioned ciphertext.
4. Rotate each existing project to migrate its legacy rows.
5. Verify every secret has a non-null `encryption_key_version` before considering the legacy path removable.

The migration intentionally refuses an automatic downgrade. Dropping the project key table while ciphertext depends on it would make secrets permanently unreadable. A downgrade first requires an explicit re-encryption procedure back to the legacy format.

## Root-key providers

Development defaults to the local provider:

```text
SECRETS_ROOT_KEY_PROVIDER=local
SECRETS_MASTER_KEY=<fernet-key>
```

Production can use AWS KMS:

```text
SECRETS_ROOT_KEY_PROVIDER=aws_kms
AWS_KMS_KEY_ID=alias/envbasis
AWS_KMS_REGION=us-west-2
```

The AWS provider calls `GenerateDataKey` with `AES_256` when creating a project key and calls `Decrypt` when a project DEK is needed. Both operations use an encryption context containing the project ID and the fixed purpose `project-data-encryption-key`. A wrapped key copied to a different project therefore cannot be decrypted with the substituted context.

The application IAM role should be limited to `kms:GenerateDataKey` and `kms:Decrypt` on the configured key. It does not need permissions to create, disable, schedule deletion of, or modify policy for KMS keys.

Each project-key row records `wrapping_provider` and `wrapping_key_id`. Existing locally wrapped keys remain readable after the active provider changes, provided `SECRETS_MASTER_KEY` remains configured. Rotating a project after selecting AWS KMS creates the new version in KMS and migrates all secret ciphertext to it.

`AWS_KMS_ENDPOINT_URL` is optional and intended for controlled testing such as LocalStack. Normal AWS deployments should leave it unset.

Changing or deleting a local root key without first migrating its project keys makes those versions unreadable. Disabling or deleting the AWS KMS key has the same effect for KMS-wrapped project keys.
