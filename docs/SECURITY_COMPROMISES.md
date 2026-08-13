# Encryption and Credential Compromise Impact

This document describes the current EnvBasis security boundaries and the response required when one is breached.

## Database-only compromise

An attacker can read project names, memberships, secret names, audit metadata, encrypted secret values, wrapped project keys, and runtime-token hashes.

The attacker cannot decrypt versioned secret values without either the local root key or permission to call AWS KMS with the correct encryption context. New runtime credentials are high-entropy values stored only as SHA-256 hashes, so their plaintext cannot be recovered from the database through decryption.

The database still exposes sensitive metadata, and the attacker could modify or delete records. Restore integrity from a trusted backup, rotate potentially affected application secrets and credentials, investigate audit logs outside the compromised database, and replace database credentials.

## Application-server compromise

The application must temporarily access plaintext secrets to serve authorized requests. A fully compromised application process can use its local root key or AWS IAM permissions to unwrap project keys and can capture plaintext while it is in memory.

Treat this as a secret compromise even if the database was not directly accessed. Isolate the server, revoke its database and AWS credentials, rotate the affected provider secrets and runtime credentials, replace the application deployment, and review outbound network activity and audit records.

With AWS KMS, disabling the compromised workload's IAM role stops new decrypt operations without exporting or replacing the KMS key.

## Root-key or KMS-access compromise without the database

The root key alone does not contain project ciphertext or wrapped project keys. It becomes dangerous when combined with a database copy, backup, or future database access.

Revoke the compromised AWS IAM principal or rotate the local root key through an explicit project-key rewrapping procedure. Review database and backup access logs to determine whether the attacker also obtained encrypted data.

Do not simply replace `SECRETS_MASTER_KEY`: locally wrapped project keys must be rewrapped first or their secrets become unreadable.

## Database and root-key compromise

An attacker holding both the database contents and the applicable local root key—or sufficient AWS KMS decrypt permission—can unwrap project DEKs and decrypt all secret versions protected by those keys.

Assume complete secret disclosure. Rotate every downstream secret, revoke every runtime credential, replace database and application credentials, replace or re-policy the root key, re-encrypt project data under new project keys, and notify affected operators according to the incident-response policy.

## Runtime and machine credentials

New runtime credentials are returned once with `Cache-Control: no-store` and are stored only as hashes. EnvBasis cannot reveal or share their plaintext later. Create one credential per machine so each can be revoked independently.

Older runtime tokens may still contain `encrypted_token` for backwards compatibility. Those legacy tokens remain revealable to authorized users and become decryptable if both their database row and local root key are compromised. Replace legacy tokens with new hash-only credentials, update the consuming machines, and revoke the legacy tokens.

A token hash is not itself accepted as a bearer token. Because generated tokens contain strong random entropy, offline guessing from a stolen hash is impractical; this does not protect a plaintext token stolen from a machine, process environment, log, or network client.

## Backups and logs

Database backups have the same sensitivity as the live database. Root keys, plaintext credentials, secret values, and KMS plaintext data keys must never be written to application logs or audit metadata.

Keep security logs in a system with separate credentials and retention controls so a database attacker cannot erase the only evidence of access.
