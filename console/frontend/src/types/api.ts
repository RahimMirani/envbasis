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
  role: 'owner' | 'member';
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
  version: number;
  environment_id: string;
  environment?: string;
  updated_at: string;
  updated_by_email: string | null;
}

export interface RevealedSecret {
  key: string;
  value: string;
  version: number;
  environment_id: string;
  updated_at: string;
  updated_by_email: string | null;
  revealed_at: string;
}

export interface SecretListResponse {
  secrets: Secret[];
}

export interface PushSecretsResponse {
  changed: number;
  unchanged: number;
}

export interface PullSecretsResponse {
  secrets: Record<string, string>;
}

export interface Member {
  user_id: string;
  email: string;
  role: 'owner' | 'member';
  can_push_pull_secrets: boolean;
  joined_at: string;
}

export interface ProjectInvitation {
  id: string;
  project_id: string;
  project_name: string;
  email: string;
  role: string;
  can_push_pull_secrets: boolean;
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
  created_at: string;
  plaintext_token?: string;
}

export interface RuntimeTokenShare {
  id: string;
  email: string;
  shared_at: string;
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
}

// Request options

export interface RequestOptions {
  signal?: AbortSignal;
}
