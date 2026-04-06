import type { AuditLog } from '../types/api';

const actionLabels: Record<string, string> = {
  secret_created: 'created a secret',
  secret_updated: 'updated a secret',
  secret_deleted: 'deleted a secret',
  secrets_pushed: 'pushed secrets',
  secrets_pulled: 'pulled secrets',
  environment_created: 'created an environment',
  member_invited: 'invited a member',
  'invitation.created': 'sent a project invitation',
  'invitation.resent': 'resent a project invitation',
  'invitation.accepted': 'accepted a project invitation',
  'invitation.rejected': 'declined a project invitation',
  'invitation.revoked': 'revoked a project invitation',
  'invitation.expired': 'an invitation expired',
  'invitation.cooldown_blocked': 'invite rate limit hit',
  member_removed: 'removed a member',
  member_access_updated: 'updated member access',
  runtime_token_created: 'created a runtime token',
  runtime_token_revoked: 'revoked a runtime token',
  runtime_token_shared: 'shared a runtime token',
  runtime_token_revealed: 'revealed a runtime token',
  runtime_secrets_fetched: 'fetched runtime secrets',
  project_created: 'created the project',
  project_updated: 'updated the project',
  project_deleted: 'deleted the project',
  cli_login_approved: 'approved a CLI login',
  cli_login_denied: 'denied a CLI login',
  cli_session_created: 'started a CLI session',
  cli_session_revoked: 'revoked a CLI session',
};

const actionColors: Record<string, string> = {
  secret_created: 'accent',
  secret_updated: 'accent',
  secret_deleted: 'danger',
  secrets_pushed: 'accent',
  secrets_pulled: 'info',
  environment_created: 'success',
  member_invited: 'info',
  'invitation.created': 'info',
  'invitation.resent': 'info',
  'invitation.accepted': 'success',
  'invitation.rejected': 'warning',
  'invitation.revoked': 'danger',
  'invitation.expired': 'neutral',
  'invitation.cooldown_blocked': 'warning',
  member_removed: 'danger',
  member_access_updated: 'warning',
  runtime_token_created: 'success',
  runtime_token_revoked: 'danger',
  runtime_token_shared: 'info',
  runtime_token_revealed: 'warning',
  runtime_secrets_fetched: 'info',
  project_created: 'success',
  project_updated: 'info',
  project_deleted: 'danger',
  cli_login_approved: 'success',
  cli_login_denied: 'danger',
  cli_session_created: 'success',
  cli_session_revoked: 'danger',
};

const actionIcons: Record<string, string> = {
  secret_created: 'key',
  secret_updated: 'key',
  secret_deleted: 'key',
  secrets_pushed: 'key',
  secrets_pulled: 'pull',
  environment_created: 'environment',
  member_invited: 'member',
  'invitation.created': 'member',
  'invitation.resent': 'member',
  'invitation.accepted': 'member',
  'invitation.rejected': 'member',
  'invitation.revoked': 'member',
  'invitation.expired': 'member',
  'invitation.cooldown_blocked': 'member',
  member_removed: 'member',
  member_access_updated: 'member',
  runtime_token_created: 'token',
  runtime_token_revoked: 'revoke',
  runtime_token_shared: 'token',
  runtime_token_revealed: 'token',
  runtime_secrets_fetched: 'pull',
  project_created: 'project',
  project_updated: 'project',
  project_deleted: 'project',
  cli_login_approved: 'activity',
  cli_login_denied: 'revoke',
  cli_session_created: 'activity',
  cli_session_revoked: 'revoke',
};

export function getAuditActionLabel(action: string): string {
  return actionLabels[action] || action.replace(/_/g, ' ');
}

export function getAuditColor(action: string): string {
  return actionColors[action] || 'neutral';
}

export function getAuditIconKey(action: string): string {
  return actionIcons[action] || 'activity';
}

export function getAuditDetails(log: AuditLog): string | null {
  const metadata = log.metadata_json;
  if (!metadata) {
    return null;
  }

  if (typeof metadata.secret_key === 'string') {
    return `Key: ${metadata.secret_key}`;
  }

  if (typeof metadata.token_name === 'string') {
    return `Token: ${metadata.token_name}`;
  }

  if (typeof metadata.member_email === 'string') {
    return `Member: ${metadata.member_email}`;
  }

  if (typeof metadata.environment_name === 'string') {
    return `Environment: ${metadata.environment_name}`;
  }

  if (typeof metadata.changed === 'number' && typeof metadata.unchanged === 'number') {
    return `${metadata.changed} changed, ${metadata.unchanged} unchanged`;
  }

  if (typeof metadata.client_name === 'string') {
    return `Client: ${metadata.client_name}`;
  }

  return null;
}
