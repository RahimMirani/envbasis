import { useEffect, useMemo, useState } from 'react';
import {
  Plus,
  ShieldAlert,
  ShieldCheck,
  ShieldX,
  Copy,
  Check,
  AlertTriangle,
  Eye,
  Share2,
} from 'lucide-react';
import { useOutletContext } from 'react-router-dom';
import DashboardLoader from '../components/DashboardLoader';
import Modal from '../components/Modal';
import { useAuth } from '../auth/useAuth';
import {
  createRuntimeToken,
  listMembers,
  listRuntimeTokenShares,
  listRuntimeTokens,
  revealRuntimeToken,
  revokeRuntimeToken,
  shareRuntimeToken,
  ApiError,
} from '../lib/api';
import { formatDate, formatRelativeTime } from '../lib/format';
import type { Project, Environment, RuntimeToken, RuntimeTokenShare, Member } from '../types/api';

interface OutletContextType {
  currentProject: Project;
  currentEnv: string;
  environments: Environment[];
  canManageProject: boolean;
  onRuntimeTokenCountChanged: (delta: number) => void;
}

interface ShareState {
  token: RuntimeToken | null;
  shares: RuntimeTokenShare[];
  isLoading: boolean;
  email: string;
  error: string | null;
  isSubmitting: boolean;
}

interface TokenValueModal {
  title: string;
  plaintextToken: string;
  warning: string;
}

function getRuntimeTokenStatus(token: RuntimeToken): 'active' | 'expired' | 'revoked' {
  if (token.revoked_at) {
    return 'revoked';
  }

  if (token.expires_at && new Date(token.expires_at) <= new Date()) {
    return 'expired';
  }

  return 'active';
}

function buildExpiryValue(preset: string): string | null {
  if (preset === 'never') {
    return null;
  }

  const days = Number.parseInt(preset.replace('d', ''), 10);
  if (Number.isNaN(days) || days <= 0) {
    return null;
  }

  return new Date(Date.now() + days * 24 * 60 * 60 * 1000).toISOString();
}

function formatShareError(error: ApiError | Error | null): string {
  if (!error) {
    return 'Failed to share runtime token.';
  }

  if (error instanceof ApiError) {
    if (error.status === 404) {
      return 'User not found. They need to sign in once before you can share a token with them.';
    }

    if (
      error.status === 403 &&
      error.message === 'Runtime tokens can only be shared with project members.'
    ) {
      return 'Runtime tokens can only be shared with existing project members.';
    }

    if (error.status === 409) {
      return error.message || 'This member already has access to the token.';
    }
  }

  return error.message || 'Failed to share runtime token.';
}

function formatCreateError(error: ApiError | Error | null): string {
  if (!error) {
    return 'Failed to create runtime token.';
  }

  if (error instanceof ApiError && error.status === 409) {
    return error.message || 'An active runtime token with this name already exists.';
  }

  return error.message || 'Failed to create runtime token.';
}

export default function TokensPage() {
  const {
    currentProject,
    currentEnv,
    environments,
    canManageProject,
    onRuntimeTokenCountChanged,
  } = useOutletContext<OutletContextType>();
  const { accessToken, apiConfigError } = useAuth();
  const [tokens, setTokens] = useState<RuntimeToken[]>([]);
  const [membersById, setMembersById] = useState<Record<string, Member>>({});
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [tokenName, setTokenName] = useState('');
  const [tokenEnvId, setTokenEnvId] = useState('');
  const [tokenExpiryPreset, setTokenExpiryPreset] = useState('30d');
  const [createError, setCreateError] = useState<string | null>(null);
  const [isCreating, setIsCreating] = useState(false);
  const [shareState, setShareState] = useState<ShareState>({
    token: null,
    shares: [],
    isLoading: false,
    email: '',
    error: null,
    isSubmitting: false,
  });
  const [tokenValueModal, setTokenValueModal] = useState<TokenValueModal | null>(null);
  const [copiedToken, setCopiedToken] = useState(false);
  const [activeTokenId, setActiveTokenId] = useState<string | null>(null);

  const environmentById = useMemo(
    () => Object.fromEntries(environments.map((environment) => [environment.id, environment])),
    [environments]
  );

  const visibleTokens = useMemo(() => {
    if (currentEnv === 'all') {
      return tokens;
    }

    return tokens.filter((token) => environmentById[token.environment_id]?.name === currentEnv);
  }, [currentEnv, environmentById, tokens]);

  useEffect(() => {
    if (!accessToken) {
      return undefined;
    }

    if (apiConfigError) {
      setError(apiConfigError);
      setIsLoading(false);
      return undefined;
    }

    let isActive = true;
    const controller = new AbortController();

    async function loadTokenData() {
      setIsLoading(true);
      setError(null);

      try {
        const [tokenResponse, memberResponse] = await Promise.all([
          listRuntimeTokens(currentProject.id, accessToken!, { signal: controller.signal }),
          listMembers(currentProject.id, accessToken!, { signal: controller.signal }),
        ]);

        if (!isActive) {
          return;
        }

        setTokens(tokenResponse);
        setMembersById(
          Object.fromEntries(memberResponse.map((member) => [member.user_id, member]))
        );
      } catch (loadError) {
        if (!isActive || controller.signal.aborted) {
          return;
        }

        setError((loadError as Error).message || 'Failed to load runtime tokens.');
        setTokens([]);
      } finally {
        if (isActive) {
          setIsLoading(false);
        }
      }
    }

    void loadTokenData();

    return () => {
      isActive = false;
      controller.abort();
    };
  }, [accessToken, apiConfigError, currentProject.id]);

  const reloadTokens = async () => {
    const tokenResponse = await listRuntimeTokens(currentProject.id, accessToken!);
    setTokens(tokenResponse);
  };

  const openCreateModal = () => {
    setTokenName('');
    setTokenEnvId(
      currentEnv === 'all'
        ? environments[0]?.id || ''
        : environments.find((environment) => environment.name === currentEnv)?.id || ''
    );
    setTokenExpiryPreset('30d');
    setCreateError(null);
    setShowCreate(true);
  };

  const closeCreateModal = () => {
    if (isCreating) {
      return;
    }

    setShowCreate(false);
    setCreateError(null);
  };

  const handleCreateToken = async () => {
    const trimmedName = tokenName.trim();
    if (!trimmedName) {
      setCreateError('Token name is required.');
      return;
    }

    if (!tokenEnvId) {
      setCreateError('Select an environment.');
      return;
    }

    setIsCreating(true);
    setCreateError(null);

    try {
      const createdToken = await createRuntimeToken(
        currentProject.id,
        tokenEnvId,
        accessToken!,
        {
          name: trimmedName,
          expires_at: buildExpiryValue(tokenExpiryPreset),
        }
      );

      await reloadTokens();
      onRuntimeTokenCountChanged(1);
      setShowCreate(false);
      setCopiedToken(false);
      setTokenValueModal({
        title: 'Token Created',
        plaintextToken: createdToken.plaintext_token || '',
        warning:
          'Copy this token now. Owners and shared members can reveal active tokens later, but it is still sensitive.',
      });
    } catch (createErrorValue) {
      setCreateError(formatCreateError(createErrorValue as ApiError));
    } finally {
      setIsCreating(false);
    }
  };

  const handleRevealToken = async (token: RuntimeToken) => {
    setActiveTokenId(token.id);
    setError(null);

    try {
      const revealedToken = await revealRuntimeToken(token.id, accessToken!);
      setCopiedToken(false);
      setTokenValueModal({
        title: `Token: ${token.name}`,
        plaintextToken: revealedToken.plaintext_token || '',
        warning: 'Treat this token as sensitive. Do not expose it in logs or client-side code.',
      });
    } catch (revealErrorValue) {
      setError((revealErrorValue as Error).message || 'Failed to reveal runtime token.');
    } finally {
      setActiveTokenId(null);
    }
  };

  const handleRevokeToken = async (token: RuntimeToken) => {
    if (!window.confirm(`Revoke runtime token "${token.name}"?`)) {
      return;
    }

    setActiveTokenId(token.id);
    setError(null);

    try {
      await revokeRuntimeToken(token.id, accessToken!);
      await reloadTokens();
      onRuntimeTokenCountChanged(-1);
      if (shareState.token?.id === token.id) {
        setShareState({
          token: null,
          shares: [],
          email: '',
          error: null,
          isLoading: false,
          isSubmitting: false,
        });
      }
    } catch (revokeErrorValue) {
      setError((revokeErrorValue as Error).message || 'Failed to revoke runtime token.');
    } finally {
      setActiveTokenId(null);
    }
  };

  const openShareModal = async (token: RuntimeToken) => {
    const tokenId = token.id;

    setShareState({
      token,
      shares: [],
      isLoading: true,
      email: '',
      error: null,
      isSubmitting: false,
    });

    try {
      const shares = await listRuntimeTokenShares(token.id, accessToken!);
      setShareState((current) =>
        current.token?.id !== tokenId
          ? current
          : {
              token,
              shares,
              isLoading: false,
              email: '',
              error: null,
              isSubmitting: false,
            }
      );
    } catch (shareErrorValue) {
      setShareState((current) =>
        current.token?.id !== tokenId
          ? current
          : {
              token,
              shares: [],
              isLoading: false,
              email: '',
              error: (shareErrorValue as Error).message || 'Failed to load token shares.',
              isSubmitting: false,
            }
      );
    }
  };

  const closeShareModal = () => {
    if (shareState.isSubmitting) {
      return;
    }

    setShareState({
      token: null,
      shares: [],
      isLoading: false,
      email: '',
      error: null,
      isSubmitting: false,
    });
  };

  const handleShareToken = async () => {
    const email = shareState.email.trim().toLowerCase();
    if (!shareState.token) {
      return;
    }

    if (!email) {
      setShareState((current) => ({
        ...current,
        error: 'Recipient email is required.',
      }));
      return;
    }

    setShareState((current) => ({
      ...current,
      isSubmitting: true,
      error: null,
    }));

    try {
      const share = await shareRuntimeToken(shareState.token.id, accessToken!, { email });
      setShareState((current) => ({
        ...current,
        shares: [...current.shares, share],
        email: '',
        isSubmitting: false,
        error: null,
      }));
    } catch (shareErrorValue) {
      setShareState((current) => ({
        ...current,
        isSubmitting: false,
        error: formatShareError(shareErrorValue as ApiError),
      }));
    }
  };

  const handleCopyToken = (value: string) => {
    navigator.clipboard.writeText(value);
    setCopiedToken(true);
    setTimeout(() => setCopiedToken(false), 2000);
  };

  const statusIcon = {
    active: <ShieldCheck size={14} />,
    expired: <ShieldAlert size={14} />,
    revoked: <ShieldX size={14} />,
  };

  const statusBadge = {
    active: 'badge-success',
    expired: 'badge-warning',
    revoked: 'badge-danger',
  };

  return (
    <div className="tokens-page animate-in">
      <div className="page-header">
        <div>
          <h1 className="page-heading">Runtime Tokens</h1>
          <p className="page-subtitle">
            Tokens are used by your applications to read secrets at runtime. Treat them as
            sensitive.
          </p>
        </div>
        <div className="page-header-actions">
          <button
            className="btn btn-primary"
            onClick={openCreateModal}
            id="create-token-btn"
            disabled={!canManageProject || environments.length === 0}
          >
            <Plus size={14} />
            Create Token
          </button>
        </div>
      </div>

      {!canManageProject && (
        <p className="token-note">
          You only see runtime tokens that were shared with you. Project owners control creation,
          sharing, and revocation.
        </p>
      )}

      {error && (
        <div className="auth-status auth-status-error" role="alert">
          <span>{error}</span>
        </div>
      )}

      {environments.length === 0 ? (
        <div className="empty-state">
          <h3>No environments available</h3>
          <p>Create an environment before issuing runtime tokens.</p>
        </div>
      ) : isLoading ? (
        <DashboardLoader
          compact
          title="Loading runtime tokens"
          description="Fetching tokens available to this project membership."
        />
      ) : visibleTokens.length === 0 ? (
        <div className="empty-state">
          <h3>No runtime tokens found</h3>
          <p>
            {canManageProject
              ? currentEnv === 'all'
                ? 'Create the first runtime token for this project.'
                : `No runtime tokens found for ${currentEnv}.`
              : currentEnv === 'all'
                ? 'No runtime tokens are currently shared with you in this project.'
                : `No runtime tokens shared with you for ${currentEnv}.`}
          </p>
          {canManageProject && (
            <button className="btn btn-primary" onClick={openCreateModal}>
              <Plus size={14} />
              Create Token
            </button>
          )}
        </div>
      ) : (
        <div className="card">
          <div className="table-wrapper">
            <table id="tokens-table">
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Environment</th>
                  <th>Created By</th>
                  <th>Expires</th>
                  <th>Last Used</th>
                  <th>Status</th>
                  <th style={{ width: 220 }}>Actions</th>
                </tr>
              </thead>
              <tbody>
                {visibleTokens.map((token) => {
                  const status = getRuntimeTokenStatus(token);
                  const environment = environmentById[token.environment_id];
                  const createdBy = token.created_by
                    ? membersById[token.created_by]?.email || 'Unknown user'
                    : 'Unknown user';
                  const isBusy = activeTokenId === token.id;

                  return (
                    <tr key={token.id}>
                      <td>
                        <code className="secret-key">{token.name}</code>
                      </td>
                      <td>
                        <span
                          className={`badge badge-env badge-env-${environment?.name || 'custom'}`}
                        >
                          {environment?.name || 'Unknown'}
                        </span>
                      </td>
                      <td className="text-secondary">{createdBy}</td>
                      <td className="text-secondary">
                        {token.expires_at ? formatDate(token.expires_at) : 'Never'}
                      </td>
                      <td className="text-secondary">
                        {token.last_used_at ? formatRelativeTime(token.last_used_at) : 'Never'}
                      </td>
                      <td>
                        <span className={`badge ${statusBadge[status]}`}>
                          {statusIcon[status]}
                          {status}
                        </span>
                      </td>
                      <td>
                        <div className="token-actions">
                          <button
                            className="btn btn-ghost btn-sm"
                            onClick={() => handleRevealToken(token)}
                            disabled={status !== 'active' || isBusy}
                          >
                            <Eye size={12} />
                            Reveal
                          </button>
                          {canManageProject && (
                            <button
                              className="btn btn-ghost btn-sm"
                              onClick={() => openShareModal(token)}
                              disabled={status !== 'active' || isBusy}
                            >
                              <Share2 size={12} />
                              Share
                            </button>
                          )}
                          {canManageProject && status !== 'revoked' && (
                            <button
                              className="btn btn-danger btn-sm"
                              id={`revoke-${token.id}`}
                              onClick={() => handleRevokeToken(token)}
                              disabled={isBusy}
                            >
                              Revoke
                            </button>
                          )}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      <Modal
        isOpen={showCreate}
        onClose={closeCreateModal}
        title="Create Runtime Token"
        footer={
          <>
            <button className="btn btn-secondary" onClick={closeCreateModal} disabled={isCreating}>
              Cancel
            </button>
            <button
              className="btn btn-primary"
              onClick={handleCreateToken}
              id="confirm-create-token"
              disabled={isCreating}
            >
              <Plus size={14} />
              {isCreating ? 'Creating...' : 'Create Token'}
            </button>
          </>
        }
      >
        <div className="form-group">
          <label htmlFor="token-name-input">Token Name</label>
          <input
            id="token-name-input"
            className="input mono"
            placeholder="e.g. cli-prod-api"
            value={tokenName}
            onChange={(e) => setTokenName(e.target.value)}
            disabled={isCreating}
          />
          <p className="text-secondary">
            Use a memorable unique name. The CLI can rely on this name later.
          </p>
        </div>
        <div className="form-group">
          <label htmlFor="token-env-select">Environment</label>
          <select
            id="token-env-select"
            className="input select"
            value={tokenEnvId}
            onChange={(e) => setTokenEnvId(e.target.value)}
            disabled={currentEnv !== 'all' || isCreating}
          >
            {environments.map((env) => (
              <option key={env.id} value={env.id}>
                {env.name}
              </option>
            ))}
          </select>
        </div>
        <div className="form-group">
          <label htmlFor="token-expiry-select">Expiry</label>
          <select
            id="token-expiry-select"
            className="input select"
            value={tokenExpiryPreset}
            onChange={(e) => setTokenExpiryPreset(e.target.value)}
            disabled={isCreating}
          >
            <option value="30d">30 days</option>
            <option value="90d">90 days</option>
            <option value="180d">180 days</option>
            <option value="365d">1 year</option>
            <option value="never">Never</option>
          </select>
        </div>
        {createError && (
          <p className="tokens-error" role="alert">
            {createError}
          </p>
        )}
        <div className="token-permission-note">
          <span className="badge badge-info">Read-only</span>
          <span>
            Owners create tokens. Shared members can reveal active tokens that were shared with
            them.
          </span>
        </div>
      </Modal>

      <Modal
        isOpen={Boolean(shareState.token)}
        onClose={closeShareModal}
        title={shareState.token ? `Share ${shareState.token.name}` : 'Share Runtime Token'}
        footer={
          <>
            <button
              className="btn btn-secondary"
              onClick={closeShareModal}
              disabled={shareState.isSubmitting}
            >
              Close
            </button>
            <button
              className="btn btn-primary"
              onClick={handleShareToken}
              disabled={shareState.isSubmitting || shareState.isLoading}
            >
              <Share2 size={14} />
              {shareState.isSubmitting ? 'Sharing...' : 'Share Token'}
            </button>
          </>
        }
      >
        <div className="form-group">
          <label htmlFor="share-token-email-input">Member Email</label>
          <input
            id="share-token-email-input"
            className="input"
            type="email"
            placeholder="member@company.com"
            value={shareState.email}
            onChange={(event) =>
              setShareState((current) => ({ ...current, email: event.target.value }))
            }
            disabled={shareState.isSubmitting || shareState.isLoading}
          />
        </div>
        {shareState.error && (
          <p className="tokens-error" role="alert">
            {shareState.error}
          </p>
        )}
        <div className="token-share-list">
          <strong>Current Shares</strong>
          {shareState.isLoading ? (
            <p className="text-secondary">Loading shares...</p>
          ) : shareState.shares.length === 0 ? (
            <p className="text-secondary">This token is not shared with any members yet.</p>
          ) : (
            <div className="token-share-items">
              {shareState.shares.map((share) => (
                <span className="badge badge-neutral" key={share.id}>
                  {share.email}
                </span>
              ))}
            </div>
          )}
        </div>
      </Modal>

      <Modal
        isOpen={Boolean(tokenValueModal)}
        onClose={() => setTokenValueModal(null)}
        title={tokenValueModal?.title || 'Runtime Token'}
        footer={
          <button className="btn btn-primary" onClick={() => setTokenValueModal(null)}>
            Done
          </button>
        }
      >
        <div className="token-created-warning">
          <AlertTriangle size={18} />
          <div>
            <strong>Handle this token carefully.</strong>
            <p>{tokenValueModal?.warning}</p>
          </div>
        </div>
        <div className="token-display">
          <code className="token-value">{tokenValueModal?.plaintextToken}</code>
          <button
            className="btn btn-secondary btn-sm"
            onClick={() => handleCopyToken(tokenValueModal?.plaintextToken || '')}
          >
            {copiedToken ? (
              <>
                <Check size={12} /> Copied
              </>
            ) : (
              <>
                <Copy size={12} /> Copy
              </>
            )}
          </button>
        </div>
      </Modal>
    </div>
  );
}
