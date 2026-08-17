// Core entity types

export interface User {
  id: string;
  email: string;
  created_at: string;
}

export interface Project {
  id: string;
  name: string;
  description: string | null;
  organization_id?: string | null;
  role: 'owner' | 'member';
  audit_log_visibility: 'owner_only' | 'members' | 'specific';
  can_manage_secrets: boolean;
  can_manage_runtime_tokens: boolean;
  can_manage_team: boolean;
  can_view_audit_logs: boolean;
  environment_count: number;
  member_count: number;
  runtime_token_count: number;
  last_activity_at: string | null;
  created_at: string;
}

export interface Environment {
  id: string;
  name: string;
  project_id: string;
  created_at: string;
}

export interface Secret {
  key: string;
  path: string;
  tags: string[];
  description: string | null;
  owner: string | null;
  service: string | null;
  rotation_interval_days: number | null;
  rotate_at: string | null;
  custom_metadata: Record<string, string>;
  is_reference: boolean;
  version: number;
  environment_id: string;
  environment?: string;
  updated_at: string;
  expires_at: string | null;
  updated_by_user_id?: string | null;
  updated_by_email: string | null;
}

export interface RevealedSecret {
  key: string;
  value: string;
  path: string;
  tags: string[];
  description: string | null;
  owner: string | null;
  service: string | null;
  rotation_interval_days: number | null;
  rotate_at: string | null;
  custom_metadata: Record<string, string>;
  is_reference: boolean;
  version: number;
  environment_id: string;
  updated_at: string;
  expires_at: string | null;
  updated_by_email: string | null;
  revealed_at: string;
}

export interface SecretListResponse {
  project_id: string;
  environment_id: string;
  secrets: Secret[];
  generated_at: string;
}

export interface ProjectSecret extends Secret {
  environment_name: string;
}

export interface ProjectSecretListResponse {
  project_id: string;
  secrets: ProjectSecret[];
  next_cursor: string | null;
  generated_at: string;
}

export interface SecretFolder {
  id: string | null;
  environment_id: string;
  path: string;
  parent_path: string;
  name: string;
  description: string | null;
  created_by: string | null;
  created_at: string | null;
  synthetic: boolean;
}

export interface SecretFolderListResponse {
  project_id: string;
  environment_id: string;
  path: string;
  recursive: boolean;
  folders: SecretFolder[];
}

export interface ProjectSecretTag {
  id: string;
  project_id: string;
  name: string;
  color: string | null;
  description: string | null;
  created_by: string | null;
  created_at: string;
}

export interface PushSecretsResponse {
  changed: number;
  unchanged: number;
}

export interface PullSecretsResponse {
  secrets: Record<string, string>;
  items?: ResolvedSecretItem[];
  resolution_mode?: 'resolved' | 'unresolved';
  includes_imports?: boolean;
  resolution_errors?: string[];
}

export interface ResolvedSecretItem {
  key: string;
  value: string;
  version: number;
  source: 'local' | 'imported';
  source_environment_id: string;
  source_path: string;
  value_kind: 'literal' | 'reference';
  referenced_keys: string[];
  resolved: boolean;
  error: string | null;
}

export interface SecretImportRule {
  id: string;
  project_id: string;
  target_environment_id: string;
  target_path: string;
  source_environment_id: string;
  source_path: string;
  recursive: boolean;
  priority: number;
  enabled: boolean;
  created_by: string | null;
  created_at: string;
  updated_at: string;
}

export interface SecretVersionItem {
  key: string;
  path: string;
  version: number;
  is_deleted: boolean;
  is_reference: boolean;
  tags: string[];
  description: string | null;
  owner: string | null;
  service: string | null;
  updated_by_user_id: string | null;
  updated_by_email: string | null;
  updated_at: string;
  archived_at: string | null;
}

export interface SecretVersionListResponse {
  project_id: string;
  environment_id: string;
  key: string;
  path: string;
  versions: SecretVersionItem[];
}

export interface HistoricalSecret extends SecretVersionItem {
  value: string;
  revealed_at: string;
}

export interface SecretRollbackResult {
  key: string;
  path: string;
  source_version: number;
  version: number;
  updated_at: string;
}

export interface Member {
  user_id: string;
  email: string;
  role: 'owner' | 'member';
  can_push_pull_secrets: boolean;
  can_manage_runtime_tokens: boolean;
  can_manage_team: boolean;
  can_view_audit_logs: boolean;
  joined_at: string;
}

export interface ProjectInvitation {
  id: string;
  project_id: string;
  project_name: string;
  email: string;
  role: string;
  can_push_pull_secrets: boolean;
  can_manage_runtime_tokens: boolean;
  can_manage_team: boolean;
  can_view_audit_logs: boolean;
  invited_by_email: string | null;
  status: string;
  expires_at: string;
  last_sent_at: string | null;
  send_count: number;
  cooldown_until: string | null;
  created_at: string;
}

export interface InvitationSummary {
  id: string;
  project_id: string;
  project_name: string;
  inviter_email: string | null;
  email: string;
  role: string;
  can_push_pull_secrets: boolean;
  can_manage_runtime_tokens: boolean;
  can_manage_team: boolean;
  can_view_audit_logs: boolean;
  status: 'pending';
  expires_at: string;
  created_at: string;
}

export interface InvitationDetail {
  id: string;
  project_id: string;
  project_name: string | null;
  inviter_email: string | null;
  email: string;
  role: string;
  can_push_pull_secrets: boolean;
  can_manage_runtime_tokens: boolean;
  can_manage_team: boolean;
  can_view_audit_logs: boolean;
  status: string;
  expires_at: string;
  created_at: string;
}

export interface InviteMemberResponse {
  invitation: ProjectInvitation;
  email_sent: boolean;
  message: string | null;
}

export interface RuntimeToken {
  id: string;
  name: string;
  environment_id: string;
  created_by: string | null;
  expires_at: string | null;
  revoked_at: string | null;
  last_used_at: string | null;
  is_revealable: boolean;
  created_at: string;
  plaintext_token?: string;
}

export interface RuntimeTokenShare {
  id: string;
  runtime_token_id: string;
  user_id: string;
  email: string;
  shared_by: string | null;
  can_manage: boolean;
  created_at: string;
}

export type MachineIdentityAction = 'secrets:read' | 'proxy:use';

export interface MachineCredential {
  id: string;
  identity_id: string;
  name: string;
  auth_method: 'universal-auth';
  client_id: string;
  version: number;
  expires_at: string | null;
  overlap_expires_at: string | null;
  revoked_at: string | null;
  last_authenticated_at: string | null;
  created_at: string;
}

export interface MachineCredentialSecret extends MachineCredential {
  client_secret: string;
}

export interface MachineAuthEvent {
  id: string;
  credential_id: string | null;
  client_id: string;
  client_ip: string | null;
  success: boolean;
  reason: string;
  created_at: string;
}

export interface MachineIdentity {
  id: string;
  project_id: string | null;
  organization_id: string | null;
  environment_id: string | null;
  name: string;
  client_id: string;
  credential_version: number;
  credential_expires_at: string | null;
  access_token_ttl_seconds: number;
  allowed_actions: MachineIdentityAction[];
  allowed_secret_keys: string[] | null;
  trusted_cidrs: string[];
  created_by: string | null;
  revoked_at: string | null;
  disabled_at: string | null;
  locked_until: string | null;
  failed_auth_attempts: number;
  credentials: MachineCredential[];
  last_authenticated_at: string | null;
  last_used_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface MachineIdentityCredential extends MachineIdentity {
  client_secret: string;
}

export interface MachineIdentityWrite {
  name: string;
  environment_id: string | null;
  scope?: 'project' | 'organization';
  allowed_actions: MachineIdentityAction[];
  allowed_secret_keys: string[] | null;
  trusted_cidrs: string[];
  access_token_ttl_seconds: number;
  credential_expires_at: string | null;
}

export type ProviderName = 'openai' | 'anthropic' | 'github';

export interface ProviderCredential {
  provider: ProviderName;
  configured: boolean;
  key_last4: string;
  updated_at: string;
  updated_by: string | null;
}

export interface ProviderCredentialListResponse {
  items: ProviderCredential[];
}

export interface AuditLog {
  id: string;
  action: string;
  actor_email: string;
  environment_name: string | null;
  project_id: string | null;
  source: 'project' | 'cli_auth';
  metadata_json: Record<string, unknown> | null;
  created_at: string;
}

export interface UnifiedAuditLogListResponse {
  logs: AuditLog[];
  next_cursor: string | null;
}

export interface SecretStats {
  total_secret_count: number;
  environments: EnvironmentSecretStats[];
}

export interface EnvironmentSecretStats {
  environment_id: string;
  environment_name: string;
  secret_count: number;
  last_updated_at: string | null;
  last_activity_at: string | null;
}

// CLI Auth types

export interface CliAuthRequest {
  user_code: string;
  status: string;
  client_name?: string;
  device_name?: string;
  platform?: string;
  cli_version?: string;
  requested_scopes?: string[];
  requested_at?: string;
  expires_at?: string;
  expires_in?: number;
  approved_by_email?: string;
}

// API Error

export interface ApiErrorDetails {
  detail?: {
    message?: string;
    code?: string;
    shared_tokens?: Array<{ id: string; name: string }>;
    revealed_shared_tokens?: Array<{ id: string; name: string }>;
    members?: Array<{
      email: string;
      shared_tokens: Array<{ id: string; name: string }>;
      revealed_shared_tokens: Array<{ id: string; name: string }>;
    }>;
  };
}

export interface Webhook {
  id: string;
  project_id: string;
  url: string;
  events: string[];
  signing_secret: string;
  is_active: boolean;
  created_by: string | null;
  created_at: string;
  latest_delivery: WebhookDelivery | null;
}

export interface WebhookDelivery {
  id: string;
  webhook_id: string;
  idempotency_key: string | null;
  event: string;
  delivery_type: string;
  status: string;
  response_status: number | null;
  error_message: string | null;
  attempt_count: number;
  max_attempts: number;
  next_attempt_at: string | null;
  last_attempt_at: string | null;
  triggered_by: string | null;
  created_at: string;
  completed_at: string | null;
  attempts: WebhookDeliveryAttempt[];
}

export interface WebhookDeliveryAttempt {
  id: string;
  delivery_id: string;
  attempt_number: number;
  status: string;
  response_status: number | null;
  error_message: string | null;
  started_at: string;
  completed_at: string;
  next_retry_at: string | null;
}

export interface AccessPermission {
  id?: string;
  resource: string;
  action: string;
  effect: 'allow' | 'deny';
  environment_id: string | null;
  path: string | null;
  recursive: boolean;
}

export interface AccessRole {
  id: string;
  project_id: string | null;
  organization_id: string | null;
  name: string;
  description: string | null;
  is_builtin: boolean;
  permissions: AccessPermission[];
  created_at: string;
}

export interface AccessRoleAssignment {
  id: string;
  role_id: string;
  user_id: string | null;
  machine_identity_id: string | null;
  created_at: string;
}

export interface Organization {
  id: string;
  name: string;
  owner_id: string;
  created_at: string;
}

export interface PermissionSimulation {
  allowed: boolean;
  assigned: boolean;
  reason: string;
  matched_role_ids: string[];
  matched_permission_ids: string[];
}

export interface ApprovalStep {
  name: string;
  min_approvals: number;
  approver_user_ids: string[];
  approver_role_ids: string[];
}

export interface ApprovalPolicy {
  id: string;
  project_id: string;
  name: string;
  environment_id: string | null;
  path: string;
  recursive: boolean;
  actions: Array<'create' | 'update' | 'delete'>;
  steps: ApprovalStep[];
  prevent_self_approval: boolean;
  enabled: boolean;
  created_at: string;
  updated_at: string;
}

export interface ApprovalEvent {
  id: string;
  actor_id: string | null;
  action: string;
  step: number | null;
  comment: string | null;
  created_at: string;
}

export interface ApprovalRequest {
  id: string;
  policy_id: string;
  project_id: string;
  environment_id: string;
  path: string;
  secret_key: string;
  operation: 'create' | 'update' | 'delete';
  metadata: Record<string, unknown>;
  status: string;
  current_step: number;
  total_steps: number;
  author_id: string | null;
  created_at: string;
  resolved_at: string | null;
  events: ApprovalEvent[];
}

export interface SecretRetention {
  project_id: string;
  retain_versions: number;
  retain_days: number | null;
  archive_deleted_after_days: number | null;
}

export interface RecoveryResult {
  project_id: string;
  environment_id?: string | null;
  at: string;
  dry_run: boolean;
  changed: number;
  environments_changed: number;
  items: Array<{ key: string; path: string; action: string }>;
}

// Request options

export interface RequestOptions {
  signal?: AbortSignal;
}
