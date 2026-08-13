# EnvBasis Permission Model

This document is the authorization contract for the current EnvBasis API, console, and CLI. The backend is authoritative: hiding a button in the console or a command in the CLI is not a security control.

## Authentication and project access

Authentication proves who a user is. Authorization decides what that user may do inside a project.

Every project request first resolves the authenticated user as one of:

- `owner`: the user whose ID is stored in `projects.owner_id`.
- `member`: a user with a row in `project_members` for that project.
- non-member: no project access; project operations return `403 Forbidden`.

There is one owner per project. An invitation can only create a `member`; it cannot create or transfer the owner role.

## Member permission fields

Members receive four independent Boolean permission fields. All default to `false`.

| Field | Grants |
|---|---|
| `can_push_pull_secrets` | Reveal and pull secret values and create, update, push, or delete secrets. |
| `can_manage_runtime_tokens` | Create, update, rotate, list, and revoke machine identities and legacy runtime credentials; share or reveal only legacy encrypted tokens. |
| `can_manage_team` | List and revoke invitations, invite or revoke members, and change member permissions subject to delegation limits. |
| `can_view_audit_logs` | View and export project audit logs when project audit visibility is `specific`. |

The owner is treated as having all four permissions regardless of the values in an owner membership row.

## Operation matrix

| Operation | Owner | Member without relevant permission | Member with relevant permission |
|---|---:|---:|---:|
| View project and environment metadata | Yes | Yes | Yes |
| List members | Yes | Yes | Yes |
| List secret names, versions, and metadata | Yes | Yes | Yes |
| Reveal a secret value | Yes | No | `can_push_pull_secrets` |
| Pull/export secret values | Yes | No | `can_push_pull_secrets` |
| Push, create, update, or delete secrets | Yes | No | `can_push_pull_secrets` |
| Create, rename, or delete environments | Yes | No | No; owner only |
| Update or delete the project | Yes | No | No; owner only |
| Configure or deliver test webhooks | Yes | No | No; owner only |
| Manage runtime-credential lifecycle | Yes | No | `can_manage_runtime_tokens` |
| Manage invitations and members | Yes | No | `can_manage_team` |
| View/export audit logs | Yes | Depends on visibility | Depends on visibility |

Secret-list responses deliberately contain metadata but never a plaintext value. The CLI `--reveal` and pull flows call value-protected backend endpoints and cannot bypass this rule.

There is currently no separate secret-export API. Exporting secrets means calling the protected pull endpoint and formatting or writing its response.

## Audit-log visibility

The project owner selects one audit visibility mode:

| Mode | Effective member access |
|---|---|
| `owner_only` | No member can view audit logs, even if their stored `can_view_audit_logs` flag is `true`. |
| `members` | Every project member can view audit logs. |
| `specific` | Only members with `can_view_audit_logs=true` can view audit logs. |

Denied member attempts to access audit logs are themselves recorded in the audit log.

## Delegated team administration

The owner may grant or revoke any member permission.

A member with `can_manage_team=true` may only grant permissions that the member currently possesses. For example, a team manager without `can_push_pull_secrets` cannot grant secret access to themselves, another member, or an invitee.

This restriction applies to:

- Individual permission updates
- Bulk permission updates
- New and resent invitations
- Invitation acceptance

Invitation acceptance revalidates the inviter's current membership and permissions. An invitation is revoked if its inviter no longer manages the team, if it grants permissions the inviter no longer holds, or if it attempts to create a role other than `member`.

## Runtime-token sharing

Legacy runtime tokens may support token-specific shares:

- Owners and members with `can_manage_runtime_tokens` can see and manage all project runtime tokens.
- Other members only see runtime tokens explicitly shared with them.
- A shared member may reveal the shared token.
- A shared member may revoke that token only when the share has `can_manage=true`.

New runtime credentials are displayed once and stored only as hashes, so they cannot be revealed or shared afterward. Create a separate credential for each machine. Runtime tokens are planned to be replaced by scoped machine identities; legacy token sharing remains separate from the four project-level permissions above during that transition.

The same `can_manage_runtime_tokens` permission currently controls machine-identity administration. Possessing this permission does not let the member authenticate as an identity because its client secret is shown only when the identity is created or rotated.

## Enforcement rules

- Authorization is enforced by backend dependencies and service checks.
- Clients must never infer authorization only from console state or CLI configuration.
- Project owners cannot have their permissions changed or be revoked through member-management endpoints.
- Non-members receive `403 Forbidden` before a project operation is performed.
- Invalid or stale privilege-bearing invitations return `409 Conflict`, are revoked, and are audited.
- Permission changes and sensitive reads are written to the audit log.

## Current limitation

`can_push_pull_secrets` combines secret-value read and secret-write access. A later permission-model version should split it into narrower read, write, and environment/path scopes. Until that migration is implemented, granting this flag must be understood as granting both read and write access to every environment in the project.
