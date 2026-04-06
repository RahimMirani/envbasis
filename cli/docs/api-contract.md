# EnvBasis CLI API Contract Baseline

This file captures the backend surface the CLI is designed against. It is a typed baseline derived from `plan.md` and should be updated once backend responses are confirmed.

## Auth

- `GET /auth/me`

## Projects

- `GET /projects`
- `POST /projects`
- `GET /projects/{project_id}`
- `PATCH /projects/{project_id}`
- `DELETE /projects/{project_id}`

## Environments

- `GET /projects/{project_id}/environments`
- `POST /projects/{project_id}/environments`

## Secrets

- `POST /projects/{project_id}/environments/{environment_id}/secrets/push`
- `GET /projects/{project_id}/environments/{environment_id}/secrets/pull`
- `GET /projects/{project_id}/environments/{environment_id}/secrets`
- `GET /projects/{project_id}/secrets/stats`
- `POST /projects/{project_id}/environments/{environment_id}/secrets`
- `PATCH /projects/{project_id}/environments/{environment_id}/secrets/{key}`
- `DELETE /projects/{project_id}/environments/{environment_id}/secrets/{key}`

## Members

- `GET /projects/{project_id}/members`
- `POST /projects/{project_id}/invite` — returns `InviteMemberResponse` (pending invitation + `email_sent`)
- `GET /projects/{project_id}/invitations` — owner: list pending invitations
- `POST /projects/{project_id}/invitations/{invitation_id}/revoke` — owner: revoke pending invite
- `POST /projects/{project_id}/members/access`
- `POST /projects/{project_id}/revoke` — body includes optional `shared_token_action`: `keep_active` | `revoke_tokens`

## Invitations (recipient)

- `GET /me/invitations`
- `GET /me/invitations/by-token/{token}`
- `POST /me/invitations/{invitation_id}/accept`
- `POST /me/invitations/{invitation_id}/reject`

## Runtime Tokens

- `GET /projects/{project_id}/runtime-tokens`
- `POST /projects/{project_id}/environments/{environment_id}/runtime-tokens`
- `POST /projects/{project_id}/runtime-tokens/reveal-by-name`
- `POST /projects/{project_id}/runtime-tokens/revoke-by-name`
- `POST /runtime-tokens/{token_id}/share`
- `GET /runtime-tokens/{token_id}/shares`

## Audit Logs

- `GET /projects/{project_id}/audit-logs`

## Expected CLI Error Normalization

- `401`: You are not logged in.
- `403`: You do not have permission for this action.
- `404`: Project/environment/token not found.
- `409`: Show backend conflict text directly.
- `429`: Invite email cooldown / rate limit (see `detail.message`).

