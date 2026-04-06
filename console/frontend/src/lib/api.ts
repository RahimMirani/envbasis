import type {
  User,
  Project,
  Environment,
  Secret,
  SecretListResponse,
  PushSecretsResponse,
  PullSecretsResponse,
  Member,
  InvitationSummary,
  InvitationDetail,
  InviteMemberResponse,
  ProjectInvitation,
  RuntimeToken,
  RuntimeTokenShare,
  AuditLog,
  UnifiedAuditLogListResponse,
  SecretStats,
  CliAuthRequest,
  RequestOptions,
  ApiErrorDetails,
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
  body: { name?: string; description?: string | null },
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

// Secrets

export function listSecrets(
  projectId: string,
  environmentId: string,
  accessToken: string,
  options: RequestOptions = {}
): Promise<SecretListResponse> {
  return apiRequest<SecretListResponse>(
    `/projects/${encodePathSegment(projectId)}/environments/${encodePathSegment(environmentId)}/secrets`,
    {
      ...options,
      accessToken,
    }
  );
}

export function createSecret(
  projectId: string,
  environmentId: string,
  accessToken: string,
  body: { key: string; value: string },
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
  body: { value: string },
  options: RequestOptions = {}
): Promise<Secret> {
  return apiRequest<Secret>(
    `/projects/${encodePathSegment(projectId)}/environments/${encodePathSegment(environmentId)}/secrets/${encodePathSegment(secretKey)}`,
    {
      ...options,
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
  options: RequestOptions = {}
): Promise<void> {
  return apiRequest<void>(
    `/projects/${encodePathSegment(projectId)}/environments/${encodePathSegment(environmentId)}/secrets/${encodePathSegment(secretKey)}`,
    {
      ...options,
      method: 'DELETE',
      accessToken,
    }
  );
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
  body: { secrets: Record<string, string> },
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
  options: RequestOptions = {}
): Promise<PullSecretsResponse> {
  return apiRequest<PullSecretsResponse>(
    `/projects/${encodePathSegment(projectId)}/environments/${encodePathSegment(environmentId)}/secrets/pull`,
    {
      ...options,
      accessToken,
    }
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
  body: { email: string; role?: string; can_push_pull_secrets?: boolean },
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
  tokenId: string,
  accessToken: string,
  body: { email: string },
  options: RequestOptions = {}
): Promise<RuntimeTokenShare> {
  return apiRequest<RuntimeTokenShare>(`/runtime-tokens/${encodePathSegment(tokenId)}/share`, {
    ...options,
    method: 'POST',
    accessToken,
    body,
  });
}

export function listRuntimeTokenShares(
  tokenId: string,
  accessToken: string,
  options: RequestOptions = {}
): Promise<RuntimeTokenShare[]> {
  return apiRequest<RuntimeTokenShare[]>(`/runtime-tokens/${encodePathSegment(tokenId)}/shares`, {
    ...options,
    accessToken,
  });
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
  { limit = 100, ...options }: AuditLogsOptions = {}
): Promise<UnifiedAuditLogListResponse> {
  const params = new URLSearchParams({ limit: String(limit) });
  return apiRequest<UnifiedAuditLogListResponse>(`/audit-logs/unified?${params.toString()}`, {
    ...options,
    accessToken,
  });
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
