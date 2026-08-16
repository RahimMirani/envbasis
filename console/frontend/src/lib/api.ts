import type {
  User,
  Project,
  Environment,
  Secret,
  RevealedSecret,
  SecretListResponse,
  ProjectSecretListResponse,
  PushSecretsResponse,
  PullSecretsResponse,
  Member,
  InvitationSummary,
  InvitationDetail,
  InviteMemberResponse,
  ProjectInvitation,
  RuntimeToken,
  RuntimeTokenShare,
  MachineIdentity,
  MachineIdentityCredential,
  MachineIdentityWrite,
  ProviderCredential,
  ProviderCredentialListResponse,
  ProviderCredentialUpsert,
  ProviderName,
  MachineCredential,
  MachineCredentialSecret,
  MachineAuthEvent,
  AuditLog,
  UnifiedAuditLogListResponse,
  SecretStats,
  Webhook,
  WebhookDelivery,
  CliAuthRequest,
  RequestOptions,
  ApiErrorDetails,
  SecretFolder,
  SecretFolderListResponse,
  ProjectSecretTag,
  SecretImportRule,
  SecretVersionListResponse,
  HistoricalSecret,
  SecretRollbackResult,
  AccessRole,
  AccessRoleAssignment,
  ApprovalPolicy,
  ApprovalRequest,
  SecretRetention,
  RecoveryResult,
  Organization,
  PermissionSimulation,
} from '../types/api';

export class ApiError extends Error {
  status: number | null;
  code: string | null;
  details: ApiErrorDetails | null;

  constructor(
    message: string,
    { status, code, details }: { status?: number; code?: string; details?: ApiErrorDetails } = {}
  ) {
    super(message);
    this.name = 'ApiError';
    this.status = status ?? null;
    this.code = code ?? null;
    this.details = details ?? null;
  }
}

export function isAbortError(error: unknown): boolean {
  if (!error || typeof error !== 'object') {
    return false;
  }

  const candidate = error as { name?: string; message?: string };
  if (candidate.name === 'AbortError') {
    return true;
  }

  return typeof candidate.message === 'string' && candidate.message.includes('signal is aborted');
}

function encodePathSegment(value: string | number): string {
  return encodeURIComponent(String(value));
}

function readApiBaseUrl(): string | null {
  const value = import.meta.env.VITE_API_BASE_URL;
  return typeof value === 'string' && value.trim() ? value.trim().replace(/\/+$/, '') : null;
}

export function getApiConfigError(): string | null {
  if (!readApiBaseUrl()) {
    return 'Missing VITE_API_BASE_URL.';
  }

  return null;
}

interface BuildHeadersOptions {
  accessToken?: string;
  body?: unknown;
  headers?: HeadersInit;
}

function buildHeaders({ accessToken, body, headers }: BuildHeadersOptions): Headers {
  const nextHeaders = new Headers(headers || {});

  if (body !== undefined && !nextHeaders.has('Content-Type')) {
    nextHeaders.set('Content-Type', 'application/json');
  }

  if (accessToken && !nextHeaders.has('Authorization')) {
    nextHeaders.set('Authorization', `Bearer ${accessToken}`);
  }

  return nextHeaders;
}

async function parseResponse(response: Response): Promise<unknown> {
  const contentType = response.headers.get('content-type') || '';
  if (!contentType.includes('application/json')) {
    return null;
  }

  return response.json();
}

interface ApiRequestOptions extends RequestOptions {
  method?: string;
  accessToken?: string;
  body?: unknown;
  headers?: HeadersInit;
}

export async function apiRequest<T = unknown>(
  path: string,
  { method = 'GET', accessToken, body, headers, signal }: ApiRequestOptions = {}
): Promise<T> {
  const configError = getApiConfigError();
  if (configError) {
    throw new ApiError(configError, { code: 'missing_api_base_url' });
  }

  const response = await fetch(`${readApiBaseUrl()}${path}`, {
    method,
    headers: buildHeaders({ accessToken, body, headers }),
    body: body === undefined ? undefined : JSON.stringify(body),
    signal,
  });

  const payload = (await parseResponse(response)) as Record<string, unknown> | null;

  if (!response.ok) {
    const details = payload ?? null;
    const detail = payload?.detail as Record<string, unknown> | string | undefined;
    const message =
      (typeof detail === 'object' && detail?.message) ||
      (typeof detail === 'string' && detail) ||
      payload?.msg ||
      `Request failed with status ${response.status}.`;

    throw new ApiError(String(message), {
      status: response.status,
      code: (payload?.error_code || payload?.code) as string | undefined,
      details: details as ApiErrorDetails,
    });
  }

  return payload as T;
}

// Auth

export function getCurrentUser(accessToken: string, options: RequestOptions = {}): Promise<User> {
  return apiRequest<User>('/auth/me', {
    ...options,
    accessToken,
  });
}

// Projects

export function listProjects(accessToken: string, options: RequestOptions = {}): Promise<Project[]> {
  return apiRequest<Project[]>('/projects', {
    ...options,
    accessToken,
  });
}

export function createProject(
  accessToken: string,
  body: { name: string; description?: string | null },
  options: RequestOptions = {}
): Promise<Project> {
  return apiRequest<Project>('/projects', {
    ...options,
    method: 'POST',
    accessToken,
    body,
  });
}

export function getProject(
  projectId: string,
  accessToken: string,
  options: RequestOptions = {}
): Promise<Project> {
  return apiRequest<Project>(`/projects/${encodePathSegment(projectId)}`, {
    ...options,
    accessToken,
  });
}

export function updateProject(
  projectId: string,
  accessToken: string,
  body: { name?: string; description?: string | null; audit_log_visibility?: 'owner_only' | 'members' | 'specific'; organization_id?: string | null },
  options: RequestOptions = {}
): Promise<Project> {
  return apiRequest<Project>(`/projects/${encodePathSegment(projectId)}`, {
    ...options,
    method: 'PATCH',
    accessToken,
    body,
  });
}

export function deleteProject(
  projectId: string,
  accessToken: string,
  options: RequestOptions = {}
): Promise<void> {
  return apiRequest<void>(`/projects/${encodePathSegment(projectId)}`, {
    ...options,
    method: 'DELETE',
    accessToken,
  });
}

// Environments

export function listEnvironments(
  projectId: string,
  accessToken: string,
  options: RequestOptions = {}
): Promise<Environment[]> {
  return apiRequest<Environment[]>(`/projects/${encodePathSegment(projectId)}/environments`, {
    ...options,
    accessToken,
  });
}

export function createEnvironment(
  projectId: string,
  accessToken: string,
  body: { name: string },
  options: RequestOptions = {}
): Promise<Environment> {
  return apiRequest<Environment>(`/projects/${encodePathSegment(projectId)}/environments`, {
    ...options,
    method: 'POST',
    accessToken,
    body,
  });
}

export function renameEnvironment(
  projectId: string,
  environmentId: string,
  accessToken: string,
  body: { name: string },
  options: RequestOptions = {}
): Promise<Environment> {
  return apiRequest<Environment>(
    `/projects/${encodePathSegment(projectId)}/environments/${encodePathSegment(environmentId)}`,
    { ...options, method: 'PATCH', accessToken, body }
  );
}

export function deleteEnvironment(
  projectId: string,
  environmentId: string,
  accessToken: string,
  options: RequestOptions = {}
): Promise<void> {
  return apiRequest<void>(
    `/projects/${encodePathSegment(projectId)}/environments/${encodePathSegment(environmentId)}`,
    { ...options, method: 'DELETE', accessToken }
  );
}

// Secrets

export function listSecrets(
  projectId: string,
  environmentId: string,
  accessToken: string,
  options: RequestOptions & { key?: string; path?: string; recursive?: boolean; tags?: string[] } = {}
): Promise<SecretListResponse> {
  const { key, path, recursive, tags, ...rest } = options;
  const search = new URLSearchParams();
  if (key) search.set('key', key);
  if (path) search.set('path', path);
  if (recursive) search.set('recursive', 'true');
  tags?.forEach((tag) => search.append('tag', tag));
  const params = search.size ? `?${search.toString()}` : '';
  return apiRequest<SecretListResponse>(
    `/projects/${encodePathSegment(projectId)}/environments/${encodePathSegment(environmentId)}/secrets${params}`,
    { ...rest, accessToken }
  );
}

export function listProjectSecrets(
  projectId: string,
  accessToken: string,
  options: RequestOptions & {
    key?: string;
    environmentIds?: string[];
    limit?: number;
    cursor?: string | null;
    path?: string;
    recursive?: boolean;
    tags?: string[];
  } = {}
): Promise<ProjectSecretListResponse> {
  const { key, environmentIds, limit, cursor, path, recursive, tags, ...rest } = options;
  const params = new URLSearchParams();

  if (key) {
    params.set('key', key);
  }
  if (limit) {
    params.set('limit', String(limit));
  }
  if (cursor) {
    params.set('cursor', cursor);
  }
  if (path) params.set('path', path);
  if (recursive) params.set('recursive', 'true');
  tags?.forEach((tag) => params.append('tag', tag));
  environmentIds?.forEach((environmentId) => {
    params.append('environment_id', environmentId);
  });

  return apiRequest<ProjectSecretListResponse>(
    `/projects/${encodePathSegment(projectId)}/secrets${params.size ? `?${params.toString()}` : ''}`,
    { ...rest, accessToken }
  );
}

export function revealSecret(
  projectId: string,
  environmentId: string,
  secretKey: string,
  accessToken: string,
  options: RequestOptions & { path?: string } = {}
): Promise<RevealedSecret> {
  const { path, ...rest } = options;
  const params = path ? `?path=${encodeURIComponent(path)}` : '';
  return apiRequest<RevealedSecret>(
    `/projects/${encodePathSegment(projectId)}/environments/${encodePathSegment(environmentId)}/secrets/${encodePathSegment(secretKey)}/reveal${params}`,
    {
      ...rest,
      accessToken,
    }
  );
}

export function createSecret(
  projectId: string,
  environmentId: string,
  accessToken: string,
  body: {
    key: string;
    value: string;
    expires_at?: string | null;
    path?: string;
    tags?: string[];
    description?: string | null;
    owner?: string | null;
    service?: string | null;
    rotation_interval_days?: number | null;
    rotate_at?: string | null;
    custom_metadata?: Record<string, string>;
  },
  options: RequestOptions = {}
): Promise<Secret> {
  return apiRequest<Secret>(
    `/projects/${encodePathSegment(projectId)}/environments/${encodePathSegment(environmentId)}/secrets`,
    {
      ...options,
      method: 'POST',
      accessToken,
      body,
    }
  );
}

export function updateSecret(
  projectId: string,
  environmentId: string,
  secretKey: string,
  accessToken: string,
  body: {
    value: string;
    expires_at?: string | null;
    tags?: string[];
    description?: string | null;
    owner?: string | null;
    service?: string | null;
    rotation_interval_days?: number | null;
    rotate_at?: string | null;
    custom_metadata?: Record<string, string>;
  },
  options: RequestOptions & { path?: string } = {}
): Promise<Secret> {
  const { path, ...rest } = options;
  const params = path ? `?path=${encodeURIComponent(path)}` : '';
  return apiRequest<Secret>(
    `/projects/${encodePathSegment(projectId)}/environments/${encodePathSegment(environmentId)}/secrets/${encodePathSegment(secretKey)}${params}`,
    {
      ...rest,
      method: 'PATCH',
      accessToken,
      body,
    }
  );
}

export function deleteSecret(
  projectId: string,
  environmentId: string,
  secretKey: string,
  accessToken: string,
  options: RequestOptions & { path?: string } = {}
): Promise<void> {
  const { path, ...rest } = options;
  const params = path ? `?path=${encodeURIComponent(path)}` : '';
  return apiRequest<void>(
    `/projects/${encodePathSegment(projectId)}/environments/${encodePathSegment(environmentId)}/secrets/${encodePathSegment(secretKey)}${params}`,
    {
      ...rest,
      method: 'DELETE',
      accessToken,
    }
  );
}

export function bulkDeleteSecrets(
  projectId: string,
  accessToken: string,
  body: { items: Array<{ environment_id: string; key: string; path?: string }> },
  options: RequestOptions = {}
): Promise<void> {
  return apiRequest<void>(`/projects/${encodePathSegment(projectId)}/secrets/bulk-delete`, {
    ...options,
    method: 'POST',
    accessToken,
    body,
  });
}

export function getProjectSecretStats(
  projectId: string,
  accessToken: string,
  options: RequestOptions = {}
): Promise<SecretStats> {
  return apiRequest<SecretStats>(`/projects/${encodePathSegment(projectId)}/secrets/stats`, {
    ...options,
    accessToken,
  });
}

export function pushSecrets(
  projectId: string,
  environmentId: string,
  accessToken: string,
  body: { secrets: Record<string, string>; path?: string; tags?: string[] },
  options: RequestOptions = {}
): Promise<PushSecretsResponse> {
  return apiRequest<PushSecretsResponse>(
    `/projects/${encodePathSegment(projectId)}/environments/${encodePathSegment(environmentId)}/secrets/push`,
    {
      ...options,
      method: 'POST',
      accessToken,
      body,
    }
  );
}

export function pullSecrets(
  projectId: string,
  environmentId: string,
  accessToken: string,
  options: RequestOptions & { path?: string; recursive?: boolean; tags?: string[] } = {}
): Promise<PullSecretsResponse> {
  const { path, recursive, tags, ...rest } = options;
  const search = new URLSearchParams();
  if (path) search.set('path', path);
  if (recursive) search.set('recursive', 'true');
  tags?.forEach((tag) => search.append('tag', tag));
  const params = search.size ? `?${search.toString()}` : '';
  return apiRequest<PullSecretsResponse>(
    `/projects/${encodePathSegment(projectId)}/environments/${encodePathSegment(environmentId)}/secrets/pull${params}`,
    {
      ...rest,
      accessToken,
    }
  );
}

export function listSecretFolders(
  projectId: string,
  environmentId: string,
  accessToken: string,
  options: RequestOptions & { path?: string; recursive?: boolean } = {}
): Promise<SecretFolderListResponse> {
  const { path = '/', recursive = false, ...rest } = options;
  const search = new URLSearchParams({ path, recursive: String(recursive) });
  return apiRequest<SecretFolderListResponse>(
    `/projects/${encodePathSegment(projectId)}/environments/${encodePathSegment(environmentId)}/folders?${search.toString()}`,
    { ...rest, accessToken }
  );
}

export function createSecretFolder(
  projectId: string,
  environmentId: string,
  accessToken: string,
  body: { path: string; description?: string | null },
  options: RequestOptions = {}
): Promise<SecretFolder> {
  return apiRequest<SecretFolder>(
    `/projects/${encodePathSegment(projectId)}/environments/${encodePathSegment(environmentId)}/folders`,
    { ...options, method: 'POST', accessToken, body }
  );
}

export function listProjectSecretTags(
  projectId: string,
  accessToken: string,
  options: RequestOptions = {}
): Promise<ProjectSecretTag[]> {
  return apiRequest<ProjectSecretTag[]>(`/projects/${encodePathSegment(projectId)}/secret-tags`, {
    ...options,
    accessToken,
  });
}

export function createProjectSecretTag(
  projectId: string,
  accessToken: string,
  body: { name: string; color?: string | null; description?: string | null },
  options: RequestOptions = {}
): Promise<ProjectSecretTag> {
  return apiRequest<ProjectSecretTag>(`/projects/${encodePathSegment(projectId)}/secret-tags`, {
    ...options,
    method: 'POST',
    accessToken,
    body,
  });
}

export function listSecretImports(
  projectId: string,
  accessToken: string,
  options: RequestOptions = {}
): Promise<SecretImportRule[]> {
  return apiRequest<SecretImportRule[]>(`/projects/${encodePathSegment(projectId)}/secret-imports`, {
    ...options,
    accessToken,
  });
}

export function createSecretImport(
  projectId: string,
  accessToken: string,
  body: {
    target_environment_id: string;
    target_path: string;
    source_environment_id: string;
    source_path: string;
    recursive?: boolean;
    priority?: number;
    enabled?: boolean;
  },
  options: RequestOptions = {}
): Promise<SecretImportRule> {
  return apiRequest<SecretImportRule>(`/projects/${encodePathSegment(projectId)}/secret-imports`, {
    ...options,
    method: 'POST',
    accessToken,
    body,
  });
}

export function deleteSecretImport(
  projectId: string,
  importId: string,
  accessToken: string,
  options: RequestOptions = {}
): Promise<void> {
  return apiRequest<void>(
    `/projects/${encodePathSegment(projectId)}/secret-imports/${encodePathSegment(importId)}`,
    { ...options, method: 'DELETE', accessToken }
  );
}

export function listSecretVersions(
  projectId: string,
  environmentId: string,
  secretKey: string,
  accessToken: string,
  options: RequestOptions & { path?: string; includeArchived?: boolean } = {}
): Promise<SecretVersionListResponse> {
  const { path = '/', includeArchived = true, ...rest } = options;
  const search = new URLSearchParams({ path, include_archived: String(includeArchived) });
  return apiRequest<SecretVersionListResponse>(
    `/projects/${encodePathSegment(projectId)}/environments/${encodePathSegment(environmentId)}/secrets/${encodePathSegment(secretKey)}/versions?${search.toString()}`,
    { ...rest, accessToken }
  );
}

export function revealSecretVersion(
  projectId: string,
  environmentId: string,
  secretKey: string,
  version: number,
  accessToken: string,
  options: RequestOptions & { path?: string } = {}
): Promise<HistoricalSecret> {
  const { path = '/', ...rest } = options;
  return apiRequest<HistoricalSecret>(
    `/projects/${encodePathSegment(projectId)}/environments/${encodePathSegment(environmentId)}/secrets/${encodePathSegment(secretKey)}/versions/${version}/reveal?path=${encodeURIComponent(path)}`,
    { ...rest, accessToken }
  );
}

export function rollbackSecretVersion(
  projectId: string,
  environmentId: string,
  secretKey: string,
  version: number,
  accessToken: string,
  options: RequestOptions & { path?: string } = {}
): Promise<SecretRollbackResult> {
  const { path = '/', ...rest } = options;
  return apiRequest<SecretRollbackResult>(
    `/projects/${encodePathSegment(projectId)}/environments/${encodePathSegment(environmentId)}/secrets/${encodePathSegment(secretKey)}/versions/${version}/rollback?path=${encodeURIComponent(path)}`,
    { ...rest, method: 'POST', accessToken }
  );
}

// Members

export function listMembers(
  projectId: string,
  accessToken: string,
  options: RequestOptions = {}
): Promise<Member[]> {
  return apiRequest<Member[]>(`/projects/${encodePathSegment(projectId)}/members`, {
    ...options,
    accessToken,
  });
}

export function inviteMember(
  projectId: string,
  accessToken: string,
  body: {
    email: string;
    role?: string;
    can_push_pull_secrets?: boolean;
    can_manage_runtime_tokens?: boolean;
    can_manage_team?: boolean;
    can_view_audit_logs?: boolean;
  },
  options: RequestOptions = {}
): Promise<InviteMemberResponse> {
  return apiRequest<InviteMemberResponse>(`/projects/${encodePathSegment(projectId)}/invite`, {
    ...options,
    method: 'POST',
    accessToken,
    body,
  });
}

export function listMyInvitations(
  accessToken: string,
  options: RequestOptions = {}
): Promise<InvitationSummary[]> {
  return apiRequest<InvitationSummary[]>('/me/invitations', {
    ...options,
    accessToken,
  });
}

export function getInvitationByToken(
  token: string,
  accessToken: string,
  options: RequestOptions = {}
): Promise<InvitationDetail> {
  return apiRequest<InvitationDetail>(
    `/me/invitations/by-token/${encodePathSegment(token)}`,
    {
      ...options,
      accessToken,
    }
  );
}

export function acceptInvitation(
  invitationId: string,
  accessToken: string,
  options: RequestOptions = {}
): Promise<Member> {
  return apiRequest<Member>(`/me/invitations/${encodePathSegment(invitationId)}/accept`, {
    ...options,
    method: 'POST',
    accessToken,
  });
}

export function rejectInvitation(
  invitationId: string,
  accessToken: string,
  options: RequestOptions = {}
): Promise<void> {
  return apiRequest<void>(`/me/invitations/${encodePathSegment(invitationId)}/reject`, {
    ...options,
    method: 'POST',
    accessToken,
  });
}

export function listProjectInvitations(
  projectId: string,
  accessToken: string,
  options: RequestOptions = {}
): Promise<ProjectInvitation[]> {
  return apiRequest<ProjectInvitation[]>(
    `/projects/${encodePathSegment(projectId)}/invitations`,
    {
      ...options,
      accessToken,
    }
  );
}

export function revokeProjectInvitation(
  projectId: string,
  invitationId: string,
  accessToken: string,
  options: RequestOptions = {}
): Promise<void> {
  return apiRequest<void>(
    `/projects/${encodePathSegment(projectId)}/invitations/${encodePathSegment(invitationId)}/revoke`,
    {
      ...options,
      method: 'POST',
      accessToken,
    }
  );
}

export function updateMemberSecretAccess(
  projectId: string,
  accessToken: string,
  body: { email: string; can_push_pull_secrets: boolean },
  options: RequestOptions = {}
): Promise<Member> {
  return apiRequest<Member>(`/projects/${encodePathSegment(projectId)}/members/access`, {
    ...options,
    method: 'POST',
    accessToken,
    body,
  });
}

export function updateMemberPermissions(
  projectId: string,
  accessToken: string,
  body: {
    email: string;
    can_push_pull_secrets?: boolean;
    can_manage_runtime_tokens?: boolean;
    can_manage_team?: boolean;
    can_view_audit_logs?: boolean;
  },
  options: RequestOptions = {}
): Promise<Member> {
  return apiRequest<Member>(`/projects/${encodePathSegment(projectId)}/members/permissions`, {
    ...options,
    method: 'POST',
    accessToken,
    body,
  });
}

export function bulkUpdateMemberPermissions(
  projectId: string,
  accessToken: string,
  body: {
    emails: string[];
    can_push_pull_secrets?: boolean;
    can_manage_runtime_tokens?: boolean;
    can_manage_team?: boolean;
    can_view_audit_logs?: boolean;
  },
  options: RequestOptions = {}
): Promise<Member[]> {
  return apiRequest<Member[]>(
    `/projects/${encodePathSegment(projectId)}/members/permissions/bulk`,
    {
      ...options,
      method: 'POST',
      accessToken,
      body,
    }
  );
}

export function revokeMember(
  projectId: string,
  accessToken: string,
  body: { email: string; shared_token_action?: string },
  options: RequestOptions = {}
): Promise<void> {
  return apiRequest<void>(`/projects/${encodePathSegment(projectId)}/revoke`, {
    ...options,
    method: 'POST',
    accessToken,
    body,
  });
}

export function bulkRevokeMembers(
  projectId: string,
  accessToken: string,
  body: { emails: string[]; shared_token_action?: string },
  options: RequestOptions = {}
): Promise<void> {
  return apiRequest<void>(`/projects/${encodePathSegment(projectId)}/members/bulk-revoke`, {
    ...options,
    method: 'POST',
    accessToken,
    body,
  });
}

// Runtime Tokens

export function listRuntimeTokens(
  projectId: string,
  accessToken: string,
  options: RequestOptions = {}
): Promise<RuntimeToken[]> {
  return apiRequest<RuntimeToken[]>(`/projects/${encodePathSegment(projectId)}/runtime-tokens`, {
    ...options,
    accessToken,
  });
}

export function createRuntimeToken(
  projectId: string,
  environmentId: string,
  accessToken: string,
  body: { name: string; expires_at?: string | null },
  options: RequestOptions = {}
): Promise<RuntimeToken> {
  return apiRequest<RuntimeToken>(
    `/projects/${encodePathSegment(projectId)}/environments/${encodePathSegment(environmentId)}/runtime-tokens`,
    {
      ...options,
      method: 'POST',
      accessToken,
      body,
    }
  );
}

export function shareRuntimeToken(
  projectId: string,
  tokenId: string,
  accessToken: string,
  body: { email: string },
  options: RequestOptions = {}
): Promise<RuntimeTokenShare> {
  return apiRequest<RuntimeTokenShare>(
    `/projects/${encodePathSegment(projectId)}/runtime-tokens/${encodePathSegment(tokenId)}/share`,
    {
      ...options,
      method: 'POST',
      accessToken,
      body,
    }
  );
}

export function listRuntimeTokenShares(
  projectId: string,
  tokenId: string,
  accessToken: string,
  options: RequestOptions = {}
): Promise<RuntimeTokenShare[]> {
  return apiRequest<RuntimeTokenShare[]>(
    `/projects/${encodePathSegment(projectId)}/runtime-tokens/${encodePathSegment(tokenId)}/shares`,
    {
      ...options,
      accessToken,
    }
  );
}

export function revealRuntimeToken(
  tokenId: string,
  accessToken: string,
  options: RequestOptions = {}
): Promise<RuntimeToken> {
  return apiRequest<RuntimeToken>(`/runtime-tokens/${encodePathSegment(tokenId)}/reveal`, {
    ...options,
    method: 'POST',
    accessToken,
  });
}

export function revokeRuntimeToken(
  tokenId: string,
  accessToken: string,
  options: RequestOptions = {}
): Promise<void> {
  return apiRequest<void>(`/runtime-tokens/${encodePathSegment(tokenId)}/revoke`, {
    ...options,
    method: 'POST',
    accessToken,
  });
}

// Audit Logs

interface AuditLogsOptions extends RequestOptions {
  limit?: number;
  cursor?: string;
  projectId?: string;
  source?: 'all' | 'project' | 'cli_auth';
}

export function listAuditLogs(
  projectId: string,
  accessToken: string,
  { limit = 100, ...options }: AuditLogsOptions = {}
): Promise<AuditLog[]> {
  const params = new URLSearchParams({ limit: String(limit) });
  return apiRequest<AuditLog[]>(
    `/projects/${encodePathSegment(projectId)}/audit-logs?${params.toString()}`,
    {
      ...options,
      accessToken,
    }
  );
}

export function listUnifiedAuditLogs(
  accessToken: string,
  { limit = 100, cursor, projectId, source, ...options }: AuditLogsOptions = {}
): Promise<UnifiedAuditLogListResponse> {
  const params = new URLSearchParams({ limit: String(limit) });
  if (cursor) {
    params.set('cursor', cursor);
  }
  if (projectId) {
    params.set('project_id', projectId);
  }
  if (source && source !== 'all') {
    params.set('source', source);
  }
  return apiRequest<UnifiedAuditLogListResponse>(`/audit-logs/unified?${params.toString()}`, {
    ...options,
    accessToken,
  });
}

export async function downloadAuditLogs(
  projectId: string,
  accessToken: string,
  format: 'json' | 'csv' = 'csv'
): Promise<void> {
  const base = readApiBaseUrl() ?? '';
  const response = await fetch(
    `${base}/projects/${encodePathSegment(projectId)}/audit-logs/export?format=${format}`,
    { headers: { Authorization: `Bearer ${accessToken}` } }
  );
  if (!response.ok) {
    throw new ApiError(`Export failed with status ${response.status}.`, { status: response.status });
  }
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  const disposition = response.headers.get('content-disposition') ?? '';
  const match = /filename="([^"]+)"/.exec(disposition);
  a.href = url;
  a.download = match ? match[1] : `audit-logs.${format}`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

// Webhooks

export function listWebhooks(
  projectId: string,
  accessToken: string,
  options: RequestOptions = {}
): Promise<Webhook[]> {
  return apiRequest<Webhook[]>(`/projects/${encodePathSegment(projectId)}/webhooks`, {
    ...options,
    accessToken,
  });
}

export function createWebhook(
  projectId: string,
  accessToken: string,
  body: { url: string; events: string[] },
  options: RequestOptions = {}
): Promise<Webhook> {
  return apiRequest<Webhook>(`/projects/${encodePathSegment(projectId)}/webhooks`, {
    ...options,
    method: 'POST',
    accessToken,
    body,
  });
}

export function deleteWebhook(
  projectId: string,
  webhookId: string,
  accessToken: string,
  options: RequestOptions = {}
): Promise<void> {
  return apiRequest<void>(
    `/projects/${encodePathSegment(projectId)}/webhooks/${encodePathSegment(webhookId)}`,
    { ...options, method: 'DELETE', accessToken }
  );
}

export function listWebhookEvents(
  projectId: string,
  accessToken: string,
  options: RequestOptions = {}
): Promise<string[]> {
  return apiRequest<string[]>(`/projects/${encodePathSegment(projectId)}/webhooks/events`, {
    ...options,
    accessToken,
  });
}

export function listWebhookDeliveries(
  projectId: string,
  webhookId: string,
  accessToken: string,
  options: RequestOptions & { limit?: number } = {}
): Promise<WebhookDelivery[]> {
  const { limit, ...rest } = options;
  const params = new URLSearchParams();
  if (limit) {
    params.set('limit', String(limit));
  }

  return apiRequest<WebhookDelivery[]>(
    `/projects/${encodePathSegment(projectId)}/webhooks/${encodePathSegment(webhookId)}/deliveries${params.size ? `?${params.toString()}` : ''}`,
    {
      ...rest,
      accessToken,
    }
  );
}

export function sendTestWebhook(
  projectId: string,
  webhookId: string,
  accessToken: string,
  options: RequestOptions = {}
): Promise<WebhookDelivery> {
  return apiRequest<WebhookDelivery>(
    `/projects/${encodePathSegment(projectId)}/webhooks/${encodePathSegment(webhookId)}/test`,
    {
      ...options,
      method: 'POST',
      accessToken,
    }
  );
}

export function redeliverWebhookDelivery(
  projectId: string,
  webhookId: string,
  deliveryId: string,
  accessToken: string,
  options: RequestOptions = {}
): Promise<WebhookDelivery> {
  return apiRequest<WebhookDelivery>(
    `/projects/${encodePathSegment(projectId)}/webhooks/${encodePathSegment(webhookId)}/deliveries/${encodePathSegment(deliveryId)}/redeliver`,
    {
      ...options,
      method: 'POST',
      accessToken,
    }
  );
}

// Machine identities

export function listMachineIdentities(
  projectId: string,
  accessToken: string,
  options: RequestOptions = {}
): Promise<MachineIdentity[]> {
  return apiRequest<MachineIdentity[]>(
    `/projects/${encodePathSegment(projectId)}/machine-identities`,
    { ...options, accessToken }
  );
}

export function listProviderCredentials(
  projectId: string,
  environmentId: string,
  accessToken: string,
  options: RequestOptions = {}
): Promise<ProviderCredentialListResponse> {
  return apiRequest<ProviderCredentialListResponse>(
    `/projects/${encodePathSegment(projectId)}/environments/${encodePathSegment(environmentId)}/provider-credentials`,
    { ...options, accessToken }
  );
}

export function upsertProviderCredential(
  projectId: string,
  environmentId: string,
  accessToken: string,
  body: ProviderCredentialUpsert,
  options: RequestOptions = {}
): Promise<ProviderCredential> {
  return apiRequest<ProviderCredential>(
    `/projects/${encodePathSegment(projectId)}/environments/${encodePathSegment(environmentId)}/provider-credentials`,
    { ...options, method: 'PUT', accessToken, body }
  );
}

export function deleteProviderCredential(
  projectId: string,
  environmentId: string,
  provider: ProviderName,
  accessToken: string,
  options: RequestOptions = {}
): Promise<{ detail: string }> {
  return apiRequest<{ detail: string }>(
    `/projects/${encodePathSegment(projectId)}/environments/${encodePathSegment(environmentId)}/provider-credentials/${encodePathSegment(provider)}`,
    { ...options, method: 'DELETE', accessToken }
  );
}

export function createMachineIdentity(
  projectId: string,
  accessToken: string,
  body: MachineIdentityWrite,
  options: RequestOptions = {}
): Promise<MachineIdentityCredential> {
  return apiRequest<MachineIdentityCredential>(
    `/projects/${encodePathSegment(projectId)}/machine-identities`,
    { ...options, method: 'POST', accessToken, body }
  );
}

export function updateMachineIdentity(
  projectId: string,
  identityId: string,
  accessToken: string,
  body: Partial<MachineIdentityWrite>,
  options: RequestOptions = {}
): Promise<MachineIdentity> {
  return apiRequest<MachineIdentity>(
    `/projects/${encodePathSegment(projectId)}/machine-identities/${encodePathSegment(identityId)}`,
    { ...options, method: 'PATCH', accessToken, body }
  );
}

export function rotateMachineIdentitySecret(
  projectId: string,
  identityId: string,
  accessToken: string,
  body: {
    credential_expires_at: string | null;
    credential_id?: string;
    overlap_seconds?: number;
  },
  options: RequestOptions = {}
): Promise<MachineIdentityCredential> {
  return apiRequest<MachineIdentityCredential>(
    `/projects/${encodePathSegment(projectId)}/machine-identities/${encodePathSegment(identityId)}/rotate-secret`,
    { ...options, method: 'POST', accessToken, body }
  );
}

export function createMachineCredential(
  projectId: string,
  identityId: string,
  accessToken: string,
  body: { name: string; credential_expires_at: string | null },
  options: RequestOptions = {}
): Promise<MachineCredentialSecret> {
  return apiRequest<MachineCredentialSecret>(
    `/projects/${encodePathSegment(projectId)}/machine-identities/${encodePathSegment(identityId)}/credentials`,
    { ...options, method: 'POST', accessToken, body }
  );
}

export function revokeMachineCredential(
  projectId: string,
  identityId: string,
  credentialId: string,
  accessToken: string,
  options: RequestOptions = {}
): Promise<MachineCredential> {
  return apiRequest<MachineCredential>(
    `/projects/${encodePathSegment(projectId)}/machine-identities/${encodePathSegment(identityId)}/credentials/${encodePathSegment(credentialId)}`,
    { ...options, method: 'DELETE', accessToken }
  );
}

function updateMachineIdentityStatus(
  action: 'disable' | 'enable' | 'unlock',
  projectId: string,
  identityId: string,
  accessToken: string,
  options: RequestOptions = {}
): Promise<MachineIdentity> {
  return apiRequest<MachineIdentity>(
    `/projects/${encodePathSegment(projectId)}/machine-identities/${encodePathSegment(identityId)}/${action}`,
    { ...options, method: 'POST', accessToken }
  );
}

export const disableMachineIdentity = (
  projectId: string,
  identityId: string,
  accessToken: string,
  options: RequestOptions = {}
) => updateMachineIdentityStatus('disable', projectId, identityId, accessToken, options);

export const enableMachineIdentity = (
  projectId: string,
  identityId: string,
  accessToken: string,
  options: RequestOptions = {}
) => updateMachineIdentityStatus('enable', projectId, identityId, accessToken, options);

export const unlockMachineIdentity = (
  projectId: string,
  identityId: string,
  accessToken: string,
  options: RequestOptions = {}
) => updateMachineIdentityStatus('unlock', projectId, identityId, accessToken, options);

export function listMachineAuthHistory(
  projectId: string,
  identityId: string,
  accessToken: string,
  options: RequestOptions = {}
): Promise<MachineAuthEvent[]> {
  return apiRequest<MachineAuthEvent[]>(
    `/projects/${encodePathSegment(projectId)}/machine-identities/${encodePathSegment(identityId)}/auth-history`,
    { ...options, accessToken }
  );
}

export function revokeMachineIdentity(
  projectId: string,
  identityId: string,
  accessToken: string,
  options: RequestOptions = {}
): Promise<MachineIdentity> {
  return apiRequest<MachineIdentity>(
    `/projects/${encodePathSegment(projectId)}/machine-identities/${encodePathSegment(identityId)}/revoke`,
    { ...options, method: 'POST', accessToken }
  );
}

// CLI Auth

export function resolveCliAuthCode(
  code: string,
  accessToken: string,
  options: RequestOptions = {}
): Promise<CliAuthRequest> {
  return apiRequest<CliAuthRequest>('/cli/auth/resolve', {
    ...options,
    method: 'POST',
    accessToken,
    body: { user_code: code },
  });
}

export function approveCliAuthCode(
  code: string,
  accessToken: string,
  options: RequestOptions = {}
): Promise<CliAuthRequest> {
  return apiRequest<CliAuthRequest>('/cli/auth/verify', {
    ...options,
    method: 'POST',
    accessToken,
    body: { user_code: code },
  });
}

export function denyCliAuthCode(
  code: string,
  accessToken: string,
  options: RequestOptions = {}
): Promise<CliAuthRequest> {
  return apiRequest<CliAuthRequest>('/cli/auth/deny', {
    ...options,
    method: 'POST',
    accessToken,
    body: { user_code: code },
  });
}

// Phase 2 governance

export function listAccessRoles(projectId: string, accessToken: string): Promise<AccessRole[]> {
  return apiRequest(`/projects/${encodePathSegment(projectId)}/access-roles`, { accessToken });
}

export function createAccessRole(
  projectId: string,
  accessToken: string,
  body: { name: string; description?: string; organization_id?: string; permissions: Array<Omit<import('../types/api').AccessPermission, 'id'>> }
): Promise<AccessRole> {
  return apiRequest(`/projects/${encodePathSegment(projectId)}/access-roles`, { method: 'POST', accessToken, body });
}

export function listAccessAssignments(projectId: string, accessToken: string): Promise<AccessRoleAssignment[]> {
  return apiRequest(`/projects/${encodePathSegment(projectId)}/access-assignments`, { accessToken });
}

export function createAccessAssignment(projectId: string, accessToken: string, body: { role_id: string; user_id?: string; machine_identity_id?: string }): Promise<AccessRoleAssignment> {
  return apiRequest(`/projects/${encodePathSegment(projectId)}/access-assignments`, { method: 'POST', accessToken, body });
}

export function deleteAccessAssignment(projectId: string, assignmentId: string, accessToken: string): Promise<void> {
  return apiRequest(`/projects/${encodePathSegment(projectId)}/access-assignments/${encodePathSegment(assignmentId)}`, { method: 'DELETE', accessToken });
}

export function listApprovalPolicies(projectId: string, accessToken: string): Promise<ApprovalPolicy[]> {
  return apiRequest(`/projects/${encodePathSegment(projectId)}/approval-policies`, { accessToken });
}

export function createApprovalPolicy(projectId: string, accessToken: string, body: Omit<ApprovalPolicy, 'id' | 'project_id' | 'created_at' | 'updated_at'>): Promise<ApprovalPolicy> {
  return apiRequest(`/projects/${encodePathSegment(projectId)}/approval-policies`, { method: 'POST', accessToken, body });
}

export function listApprovalRequests(projectId: string, accessToken: string): Promise<ApprovalRequest[]> {
  return apiRequest(`/projects/${encodePathSegment(projectId)}/approval-requests`, { accessToken });
}

export function actOnApprovalRequest(projectId: string, requestId: string, accessToken: string, body: { action: 'approve' | 'reject' | 'cancel' | 'comment'; comment?: string }): Promise<ApprovalRequest> {
  return apiRequest(`/projects/${encodePathSegment(projectId)}/approval-requests/${encodePathSegment(requestId)}/actions`, { method: 'POST', accessToken, body });
}

export function getSecretRetention(projectId: string, accessToken: string): Promise<SecretRetention> {
  return apiRequest(`/projects/${encodePathSegment(projectId)}/secret-retention`, { accessToken });
}

export function updateSecretRetention(projectId: string, accessToken: string, body: { retain_versions: number; retain_days: number | null; archive_deleted_after_days: number | null }): Promise<SecretRetention> {
  return apiRequest(`/projects/${encodePathSegment(projectId)}/secret-retention`, { method: 'PATCH', accessToken, body });
}

export function recoverEnvironmentSecrets(projectId: string, environmentId: string, accessToken: string, body: { at: string; path: string; recursive: boolean; dry_run: boolean }): Promise<RecoveryResult> {
  return apiRequest(`/projects/${encodePathSegment(projectId)}/environments/${encodePathSegment(environmentId)}/secrets/recovery`, { method: 'POST', accessToken, body });
}

export function listOrganizations(accessToken: string): Promise<Organization[]> {
  return apiRequest('/organizations', { accessToken });
}

export function createOrganization(accessToken: string, body: { name: string }): Promise<Organization> {
  return apiRequest('/organizations', { method: 'POST', accessToken, body });
}

export function simulatePermission(projectId: string, accessToken: string, body: { user_id?: string; machine_identity_id?: string; resource: string; action: string; environment_id?: string | null; path?: string | null }): Promise<PermissionSimulation> {
  return apiRequest(`/projects/${encodePathSegment(projectId)}/permissions/simulate`, { method: 'POST', accessToken, body });
}

export function createApprovalRequest(projectId: string, accessToken: string, body: { environment_id: string; path: string; secret_key: string; operation: 'create' | 'update' | 'delete'; value?: string; metadata?: Record<string, unknown>; comment?: string }): Promise<ApprovalRequest> {
  return apiRequest(`/projects/${encodePathSegment(projectId)}/approval-requests`, { method: 'POST', accessToken, body });
}
