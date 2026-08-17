import { useEffect, useMemo, useRef, useState } from 'react';
import { Navigate, useOutletContext } from 'react-router-dom';
import {
  Check,
  Copy,
  KeyRound,
  History,
  LockOpen,
  Pencil,
  Plus,
  RefreshCw,
  RotateCw,
  ShieldCheck,
  ShieldOff,
} from 'lucide-react';
import ConfirmDialog from '../components/ConfirmDialog';
import Modal from '../components/Modal';
import SectionLoader from '../components/SectionLoader';
import { useAuth } from '../auth/useAuth';
import {
  createMachineIdentity,
  createMachineCredential,
  disableMachineIdentity,
  enableMachineIdentity,
  isAbortError,
  listMachineIdentities,
  listMachineAuthHistory,
  revokeMachineCredential,
  revokeMachineIdentity,
  rotateMachineIdentitySecret,
  unlockMachineIdentity,
  updateMachineIdentity,
} from '../lib/api';
import { formatDate, formatRelativeTime } from '../lib/format';
import type { ProjectPageCacheApi } from '../lib/projectPageCache';
import type {
  Environment,
  MachineIdentity,
  MachineIdentityCredential,
  MachineIdentityWrite,
  MachineCredential,
  MachineCredentialSecret,
  MachineAuthEvent,
  Project,
} from '../types/api';

interface OutletContextType {
  currentProject: Project;
  environments: Environment[];
  currentEnv: string;
  pageCache: ProjectPageCacheApi;
}

type KeyScopeMode = 'all' | 'patterns' | 'none';

interface IdentityFormState {
  name: string;
  scope: 'project' | 'organization';
  environmentId: string;
  canReadSecrets: boolean;
  keyScopeMode: KeyScopeMode;
  keyPatterns: string;
  tokenTtlSeconds: string;
  credentialExpiresAt: string;
  trustedCidrs: string;
}

interface IdentityFormFieldsProps {
  state: IdentityFormState;
  environments: Environment[];
  disabled: boolean;
  allowOrganizationScope: boolean;
  editing: boolean;
  onChange: (next: IdentityFormState) => void;
  nameInputRef?: React.RefObject<HTMLInputElement | null>;
}

interface CredentialModalProps {
  credential: MachineIdentityCredential | MachineCredentialSecret | null;
  title: string;
  onClose: () => void;
}

const DEFAULT_ACCESS_TOKEN_TTL_SECONDS = '3600';

function createEmptyForm(environmentId = ''): IdentityFormState {
  return {
    name: '',
    scope: 'project',
    environmentId,
    canReadSecrets: true,
    keyScopeMode: 'all',
    keyPatterns: '',
    tokenTtlSeconds: DEFAULT_ACCESS_TOKEN_TTL_SECONDS,
    credentialExpiresAt: '',
    trustedCidrs: '',
  };
}

function toDateTimeLocal(value: string | null): string {
  if (!value) {
    return '';
  }

  const date = new Date(value);
  const timezoneOffset = date.getTimezoneOffset() * 60_000;
  return new Date(date.getTime() - timezoneOffset).toISOString().slice(0, 16);
}

function toIsoDateTime(value: string): string | null {
  return value ? new Date(value).toISOString() : null;
}

function splitScopeValues(value: string): string[] {
  return [...new Set(value.split(/[\n,]/).map((item) => item.trim()).filter(Boolean))];
}

function formFromIdentity(identity: MachineIdentity): IdentityFormState {
  const patterns = identity.allowed_secret_keys;
  return {
    name: identity.name,
    scope: identity.organization_id ? 'organization' : 'project',
    environmentId: identity.environment_id ?? '',
    canReadSecrets: identity.allowed_actions.includes('secrets:read'),
    keyScopeMode: patterns === null ? 'all' : patterns.length === 0 ? 'none' : 'patterns',
    keyPatterns: patterns?.join('\n') ?? '',
    tokenTtlSeconds: String(identity.access_token_ttl_seconds),
    credentialExpiresAt: toDateTimeLocal(identity.credential_expires_at),
    trustedCidrs: identity.trusted_cidrs.join('\n'),
  };
}

function withoutClientSecret(credential: MachineIdentityCredential): MachineIdentity {
  const { client_secret: _clientSecret, ...identity } = credential;
  return identity;
}

function buildWritePayload(state: IdentityFormState): MachineIdentityWrite {
  const allowedSecretKeys =
    state.keyScopeMode === 'all'
      ? null
      : state.keyScopeMode === 'none'
        ? []
        : splitScopeValues(state.keyPatterns);

  return {
    name: state.name.trim(),
    environment_id: state.scope === 'project' ? state.environmentId : null,
    scope: state.scope,
    allowed_actions: state.canReadSecrets ? ['secrets:read'] : [],
    allowed_secret_keys: allowedSecretKeys,
    trusted_cidrs: splitScopeValues(state.trustedCidrs),
    access_token_ttl_seconds: Number(state.tokenTtlSeconds),
    credential_expires_at: toIsoDateTime(state.credentialExpiresAt),
  };
}

function validateForm(state: IdentityFormState): string | null {
  if (!state.name.trim()) {
    return 'Identity name is required.';
  }
  if (state.scope === 'project' && !state.environmentId) {
    return 'Select an environment.';
  }
  if (!state.canReadSecrets) {
    return 'Select at least one allowed action.';
  }
  if (state.keyScopeMode === 'patterns' && splitScopeValues(state.keyPatterns).length === 0) {
    return 'Add at least one key pattern or choose a different key scope.';
  }

  const ttl = Number(state.tokenTtlSeconds);
  if (!Number.isInteger(ttl) || ttl < 300 || ttl > 86_400) {
    return 'Access-token lifetime must be between 300 and 86,400 seconds.';
  }
  if (state.credentialExpiresAt && Number.isNaN(new Date(state.credentialExpiresAt).getTime())) {
    return 'Choose a valid credential expiry.';
  }
  return null;
}

function getIdentityStatus(identity: MachineIdentity): 'active' | 'expired' | 'revoked' | 'disabled' | 'locked' {
  if (identity.revoked_at) {
    return 'revoked';
  }
  if (identity.disabled_at) {
    return 'disabled';
  }
  if (identity.locked_until && new Date(identity.locked_until).getTime() > Date.now()) {
    return 'locked';
  }
  if (
    identity.credential_expires_at &&
    new Date(identity.credential_expires_at).getTime() <= Date.now()
  ) {
    return 'expired';
  }
  return 'active';
}

function formatActivityTime(value: string | null): string {
  return value ? formatRelativeTime(value) : 'Never';
}

function IdentityFormFields({
  state,
  environments,
  disabled,
  allowOrganizationScope,
  editing,
  onChange,
  nameInputRef,
}: IdentityFormFieldsProps) {
  const setField = <K extends keyof IdentityFormState>(key: K, value: IdentityFormState[K]) => {
    onChange({ ...state, [key]: value });
  };

  return (
    <>
      <div className="machine-form-grid">
        <div className="form-group">
          <label htmlFor="machine-identity-name">Identity name</label>
          <input
            id="machine-identity-name"
            ref={nameInputRef}
            className="input"
            placeholder="production-api"
            value={state.name}
            onChange={(event) => setField('name', event.target.value)}
            disabled={disabled}
          />
        </div>
        <div className="form-group">
          <label htmlFor="machine-identity-scope">Identity scope</label>
          <select
            id="machine-identity-scope"
            className="input select"
            value={state.scope}
            onChange={(event) => setField('scope', event.target.value as IdentityFormState['scope'])}
            disabled={disabled || editing}
          >
            <option value="project">This project</option>
            {allowOrganizationScope ? <option value="organization">Entire organization</option> : null}
          </select>
          <p className="form-helper">Organization identities use role assignments in each project.</p>
        </div>
        <div className="form-group">
          <label htmlFor="machine-identity-environment">Environment</label>
          <select
            id="machine-identity-environment"
            className="input select"
            value={state.environmentId}
            onChange={(event) => setField('environmentId', event.target.value)}
            disabled={disabled || state.scope === 'organization'}
          >
            <option value="">{state.scope === 'organization' ? 'Selected when authenticating' : 'Select environment'}</option>
            {environments.map((environment) => (
              <option key={environment.id} value={environment.id}>
                {environment.name}
              </option>
            ))}
          </select>
        </div>
      </div>

      <fieldset className="machine-fieldset" disabled={disabled}>
        <legend>Allowed actions</legend>
        <label className="machine-check-row">
          <input
            type="checkbox"
            checked={state.canReadSecrets}
            onChange={(event) => setField('canReadSecrets', event.target.checked)}
          />
          <span>
            <strong className="mono">secrets:read</strong>
            <small>Fetch allowed secrets from the selected environment.</small>
          </span>
        </label>
      </fieldset>

      <div className="form-group">
        <label htmlFor="machine-key-scope">Secret-key scope</label>
        <select
          id="machine-key-scope"
          className="input select"
          value={state.keyScopeMode}
          onChange={(event) => setField('keyScopeMode', event.target.value as KeyScopeMode)}
          disabled={disabled}
        >
          <option value="all">All keys in this environment</option>
          <option value="patterns">Only matching key patterns</option>
          <option value="none">No secret keys</option>
        </select>
      </div>
      {state.keyScopeMode === 'patterns' ? (
        <div className="form-group">
          <label htmlFor="machine-key-patterns">Allowed key patterns</label>
          <textarea
            id="machine-key-patterns"
            className="input mono machine-scope-input"
            placeholder={'DATABASE_*\nOPENAI_API_KEY'}
            value={state.keyPatterns}
            onChange={(event) => setField('keyPatterns', event.target.value)}
            disabled={disabled}
          />
          <p className="form-helper">One glob pattern per line or comma-separated.</p>
        </div>
      ) : null}

      <div className="machine-form-grid">
        <div className="form-group">
          <label htmlFor="machine-token-ttl">Access-token lifetime (seconds)</label>
          <input
            id="machine-token-ttl"
            className="input mono"
            type="number"
            min="300"
            max="86400"
            step="60"
            value={state.tokenTtlSeconds}
            onChange={(event) => setField('tokenTtlSeconds', event.target.value)}
            disabled={disabled}
          />
          <p className="form-helper">Short-lived token: 300 seconds to 24 hours.</p>
        </div>
        <div className="form-group">
          <label htmlFor="machine-credential-expiry">Client credential expiry</label>
          <input
            id="machine-credential-expiry"
            className="input"
            type="datetime-local"
            value={state.credentialExpiresAt}
            onChange={(event) => setField('credentialExpiresAt', event.target.value)}
            disabled={disabled}
          />
          <p className="form-helper">Leave empty for no automatic expiry.</p>
        </div>
      </div>

      <div className="form-group">
        <label htmlFor="machine-trusted-cidrs">Trusted IP addresses and CIDRs</label>
        <textarea
          id="machine-trusted-cidrs"
          className="input mono machine-scope-input"
          placeholder={'203.0.113.24/32\n2001:db8::/48'}
          value={state.trustedCidrs}
          onChange={(event) => setField('trustedCidrs', event.target.value)}
          disabled={disabled}
        />
        <p className="form-helper">One IPv4/IPv6 CIDR per line. Empty permits any source IP.</p>
      </div>
    </>
  );
}

function CredentialModal({ credential, title, onClose }: CredentialModalProps) {
  const [copied, setCopied] = useState<'id' | 'secret' | 'both' | null>(null);

  useEffect(() => {
    if (!credential) {
      setCopied(null);
    }
  }, [credential]);

  const copyValue = async (kind: 'id' | 'secret' | 'both', value: string) => {
    await navigator.clipboard.writeText(value);
    setCopied(kind);
    window.setTimeout(() => setCopied(null), 2000);
  };

  if (!credential) {
    return null;
  }

  const dotenv = `ENVBASIS_CLIENT_ID=${credential.client_id}\nENVBASIS_CLIENT_SECRET=${credential.client_secret}`;

  return (
    <Modal
      isOpen
      onClose={onClose}
      title={title}
      footer={
        <button type="button" className="btn btn-primary" onClick={onClose}>
          I saved the credential
        </button>
      }
    >
      <div className="token-created-warning" role="status">
        <KeyRound size={18} />
        <div>
          <strong>Copy the client secret now</strong>
          <p>EnvBasis stores only its hash. Closing this dialog permanently hides it.</p>
        </div>
      </div>

      <div className="machine-credential-field">
        <span>Client ID</span>
        <div className="token-display">
          <code className="token-value">{credential.client_id}</code>
          <button
            className="btn btn-secondary btn-sm"
            onClick={() => void copyValue('id', credential.client_id)}
          >
            {copied === 'id' ? <Check size={13} /> : <Copy size={13} />}
            Copy
          </button>
        </div>
      </div>
      <div className="machine-credential-field">
        <span>Client secret</span>
        <div className="token-display">
          <code className="token-value">{credential.client_secret}</code>
          <button
            className="btn btn-secondary btn-sm"
            onClick={() => void copyValue('secret', credential.client_secret)}
          >
            {copied === 'secret' ? <Check size={13} /> : <Copy size={13} />}
            Copy
          </button>
        </div>
      </div>
      <button
        className="btn btn-secondary machine-copy-both"
        onClick={() => void copyValue('both', dotenv)}
      >
        {copied === 'both' ? <Check size={14} /> : <Copy size={14} />}
        Copy both as environment variables
      </button>
    </Modal>
  );
}

export default function MachineIdentitiesPage() {
  const { currentProject, environments, currentEnv, pageCache } =
    useOutletContext<OutletContextType>();
  const { accessToken, apiConfigError } = useAuth();
  const canManageMachineIdentities = currentProject.can_manage_runtime_tokens;
  const cacheKey = `machine-identities:${currentProject.id}`;
  const cachedIdentities = pageCache.get<MachineIdentity[]>(cacheKey);
  const nameInputRef = useRef<HTMLInputElement>(null);

  const [identities, setIdentities] = useState<MachineIdentity[]>(() => cachedIdentities ?? []);
  const [isLoading, setIsLoading] = useState(() => !cachedIdentities);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [showCreate, setShowCreate] = useState(false);
  const [form, setForm] = useState<IdentityFormState>(() => createEmptyForm());
  const [editingIdentity, setEditingIdentity] = useState<MachineIdentity | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const [isSaving, setIsSaving] = useState(false);

  const [credential, setCredential] = useState<MachineIdentityCredential | MachineCredentialSecret | null>(null);
  const [credentialTitle, setCredentialTitle] = useState('Machine identity created');
  const [rotatingIdentity, setRotatingIdentity] = useState<MachineIdentity | null>(null);
  const [rotatingCredential, setRotatingCredential] = useState<MachineCredential | null>(null);
  const [rotationExpiry, setRotationExpiry] = useState('');
  const [rotationOverlapSeconds, setRotationOverlapSeconds] = useState('3600');
  const [rotationError, setRotationError] = useState<string | null>(null);
  const [isRotating, setIsRotating] = useState(false);

  const [identityPendingRevoke, setIdentityPendingRevoke] = useState<MachineIdentity | null>(null);
  const [revokeError, setRevokeError] = useState<string | null>(null);
  const [isRevoking, setIsRevoking] = useState(false);
  const [credentialIdentity, setCredentialIdentity] = useState<MachineIdentity | null>(null);
  const [newCredentialName, setNewCredentialName] = useState('default');
  const [newCredentialExpiry, setNewCredentialExpiry] = useState('');
  const [credentialActionError, setCredentialActionError] = useState<string | null>(null);
  const [isCredentialActionBusy, setIsCredentialActionBusy] = useState(false);
  const [historyIdentity, setHistoryIdentity] = useState<MachineIdentity | null>(null);
  const [authHistory, setAuthHistory] = useState<MachineAuthEvent[]>([]);
  const [historyError, setHistoryError] = useState<string | null>(null);
  const [isHistoryLoading, setIsHistoryLoading] = useState(false);
  const [statusActionId, setStatusActionId] = useState<string | null>(null);

  const environmentById = useMemo(
    () => new Map(environments.map((environment) => [environment.id, environment.name])),
    [environments]
  );

  const loadIdentities = async (showSpinner = false, signal?: AbortSignal) => {
    if (!accessToken || !canManageMachineIdentities) {
      setIsLoading(false);
      return;
    }
    if (apiConfigError) {
      setError(apiConfigError);
      setIsLoading(false);
      return;
    }
    if (cachedIdentities && !showSpinner) {
      setIsLoading(false);
      return;
    }

    showSpinner ? setIsRefreshing(true) : setIsLoading(true);
    setError(null);
    try {
      const response = await listMachineIdentities(currentProject.id, accessToken, { signal });
      if (signal?.aborted) {
        return;
      }
      setIdentities(response);
      pageCache.set(cacheKey, response);
    } catch (loadError) {
      if (!signal?.aborted && !isAbortError(loadError)) {
        setError((loadError as Error).message || 'Failed to load machine identities.');
      }
    } finally {
      if (!signal?.aborted) {
        setIsLoading(false);
        setIsRefreshing(false);
      }
    }
  };

  useEffect(() => {
    const controller = new AbortController();
    void loadIdentities(false, controller.signal);
    return () => controller.abort();
  }, [accessToken, apiConfigError, canManageMachineIdentities, currentProject.id]);

  useEffect(() => {
    if (!isLoading && !error) {
      pageCache.set(cacheKey, identities);
    }
  }, [cacheKey, error, identities, isLoading, pageCache]);

  if (!canManageMachineIdentities) {
    return <Navigate to={`/projects/${currentProject.id}/overview`} replace />;
  }

  const defaultEnvironmentId =
    currentEnv === 'all'
      ? environments[0]?.id ?? ''
      : environments.find((environment) => environment.name === currentEnv)?.id ?? '';

  const openCreate = () => {
    setForm(createEmptyForm(defaultEnvironmentId));
    setFormError(null);
    setShowCreate(true);
  };

  const openEdit = (identity: MachineIdentity) => {
    setEditingIdentity(identity);
    setForm(formFromIdentity(identity));
    setFormError(null);
  };

  const closeForm = () => {
    if (isSaving) {
      return;
    }
    setShowCreate(false);
    setEditingIdentity(null);
    setFormError(null);
  };

  const handleSave = async () => {
    const validationError = validateForm(form);
    if (validationError) {
      setFormError(validationError);
      return;
    }

    setIsSaving(true);
    setFormError(null);
    try {
      const payload = buildWritePayload(form);
      if (editingIdentity) {
        const updated = await updateMachineIdentity(
          currentProject.id,
          editingIdentity.id,
          accessToken!,
          payload
        );
        setIdentities((current) =>
          current.map((identity) => (identity.id === updated.id ? updated : identity))
        );
        setEditingIdentity(null);
      } else {
        const created = await createMachineIdentity(currentProject.id, accessToken!, payload);
        setIdentities((current) => [...current, withoutClientSecret(created)]);
        setShowCreate(false);
        setCredentialTitle('Machine identity created');
        setCredential(created);
      }
    } catch (saveError) {
      setFormError((saveError as Error).message || 'Failed to save machine identity.');
    } finally {
      setIsSaving(false);
    }
  };

  const openRotate = (identity: MachineIdentity, selectedCredential?: MachineCredential) => {
    setRotatingIdentity(identity);
    setRotatingCredential(selectedCredential ?? null);
    setRotationExpiry(toDateTimeLocal(selectedCredential?.expires_at ?? identity.credential_expires_at));
    setRotationOverlapSeconds('3600');
    setRotationError(null);
  };

  const handleRotate = async () => {
    if (!rotatingIdentity) {
      return;
    }
    const overlapSeconds = Number(rotationOverlapSeconds);
    if (rotationExpiry && Number.isNaN(new Date(rotationExpiry).getTime())) {
      setRotationError('Choose a valid credential expiry.');
      return;
    }
    if (!Number.isInteger(overlapSeconds) || overlapSeconds < 0 || overlapSeconds > 604800) {
      setRotationError('Overlap must be between 0 and 604,800 seconds.');
      return;
    }

    setIsRotating(true);
    setRotationError(null);
    try {
      const rotated = await rotateMachineIdentitySecret(
        currentProject.id,
        rotatingIdentity.id,
        accessToken!,
        {
          credential_expires_at: toIsoDateTime(rotationExpiry),
          credential_id: rotatingCredential?.id,
          overlap_seconds: overlapSeconds,
        }
      );
      const updatedIdentity = withoutClientSecret(rotated);
      setIdentities((current) =>
        current.map((identity) =>
          identity.id === updatedIdentity.id ? updatedIdentity : identity
        )
      );
      setRotatingIdentity(null);
      setRotatingCredential(null);
      setCredentialTitle('Client secret rotated');
      setCredential(rotated);
    } catch (rotateError) {
      setRotationError((rotateError as Error).message || 'Failed to rotate client secret.');
    } finally {
      setIsRotating(false);
    }
  };

  const handleCreateCredential = async () => {
    if (!credentialIdentity || !newCredentialName.trim()) {
      setCredentialActionError('Credential name is required.');
      return;
    }
    setIsCredentialActionBusy(true);
    setCredentialActionError(null);
    try {
      const created = await createMachineCredential(
        currentProject.id,
        credentialIdentity.id,
        accessToken!,
        { name: newCredentialName.trim(), credential_expires_at: toIsoDateTime(newCredentialExpiry) }
      );
      setCredentialIdentity(null);
      setCredentialTitle('Additional credential created');
      setCredential(created);
      await loadIdentities(true);
    } catch (actionError) {
      setCredentialActionError((actionError as Error).message || 'Failed to create credential.');
    } finally {
      setIsCredentialActionBusy(false);
    }
  };

  const handleRevokeCredential = async (identity: MachineIdentity, item: MachineCredential) => {
    if (!window.confirm(`Revoke credential “${item.name}”?`)) return;
    setStatusActionId(item.id);
    setError(null);
    try {
      await revokeMachineCredential(currentProject.id, identity.id, item.id, accessToken!);
      await loadIdentities(true);
    } catch (actionError) {
      setError((actionError as Error).message || 'Failed to revoke credential.');
    } finally {
      setStatusActionId(null);
    }
  };

  const handleIdentityStatus = async (
    identity: MachineIdentity,
    action: 'disable' | 'enable' | 'unlock'
  ) => {
    setStatusActionId(identity.id);
    setError(null);
    try {
      const request = action === 'disable' ? disableMachineIdentity : action === 'enable' ? enableMachineIdentity : unlockMachineIdentity;
      const updated = await request(currentProject.id, identity.id, accessToken!);
      setIdentities((current) => current.map((item) => item.id === updated.id ? updated : item));
    } catch (actionError) {
      setError((actionError as Error).message || `Failed to ${action} machine identity.`);
    } finally {
      setStatusActionId(null);
    }
  };

  const openHistory = async (identity: MachineIdentity) => {
    setHistoryIdentity(identity);
    setAuthHistory([]);
    setHistoryError(null);
    setIsHistoryLoading(true);
    try {
      setAuthHistory(await listMachineAuthHistory(currentProject.id, identity.id, accessToken!));
    } catch (loadError) {
      setHistoryError((loadError as Error).message || 'Failed to load authentication history.');
    } finally {
      setIsHistoryLoading(false);
    }
  };

  const handleRevoke = async () => {
    if (!identityPendingRevoke) {
      return;
    }

    setIsRevoking(true);
    setRevokeError(null);
    try {
      const revoked = await revokeMachineIdentity(
        currentProject.id,
        identityPendingRevoke.id,
        accessToken!
      );
      setIdentities((current) =>
        current.map((identity) => (identity.id === revoked.id ? revoked : identity))
      );
      setIdentityPendingRevoke(null);
    } catch (revokeFailure) {
      setRevokeError((revokeFailure as Error).message || 'Failed to revoke machine identity.');
    } finally {
      setIsRevoking(false);
    }
  };

  return (
    <div className="machine-identities-page animate-in">
      <div className="page-header">
        <div>
          <h1 className="page-heading">Machine Identities</h1>
          <p className="page-subtitle">
            Give deployed services scoped access without storing a long-lived secrets token.
          </p>
        </div>
        <div className="page-header-actions">
          <button
            className="btn btn-secondary"
            onClick={() => void loadIdentities(true)}
            disabled={isRefreshing || isLoading}
          >
            <RefreshCw size={14} className={isRefreshing ? 'icon-spin' : ''} />
            {isRefreshing ? 'Refreshing...' : 'Refresh'}
          </button>
          <button className="btn btn-primary" onClick={openCreate} disabled={!environments.length}>
            <Plus size={14} />
            Create Identity
          </button>
        </div>
      </div>

      {error ? (
        <div className="auth-status auth-status-error" role="alert">
          <span>{error}</span>
        </div>
      ) : null}

      {isLoading ? (
        <SectionLoader label="Loading machine identities" />
      ) : identities.length === 0 ? (
        <div className="empty-state">
          <ShieldCheck size={32} />
          <h3>No machine identities yet</h3>
          <p>Create one for a deployed service, CI job, or agent that needs scoped secrets.</p>
          {environments.length ? (
            <button className="btn btn-primary" onClick={openCreate}>
              <Plus size={14} />
              Create Identity
            </button>
          ) : (
            <p>Create an environment before adding a machine identity.</p>
          )}
        </div>
      ) : (
        <div className="machine-identity-grid">
          {identities.map((identity) => {
            const status = getIdentityStatus(identity);
            const environmentName = identity.organization_id
              ? 'Selected per request'
              : environmentById.get(identity.environment_id ?? '') ?? 'Unknown';
            const keyScope =
              identity.allowed_secret_keys === null
                ? 'All keys'
                : identity.allowed_secret_keys.length === 0
                  ? 'No keys'
                  : identity.allowed_secret_keys.join(', ');

            return (
              <article className="card machine-identity-card" key={identity.id}>
                <div className="machine-identity-header">
                  <div>
                    <div className="machine-identity-title-row">
                      <h3>{identity.name}</h3>
                      <span className={`badge machine-status machine-status-${status}`}>
                        {status}
                      </span>
                    </div>
                    <code className="machine-client-id">{identity.client_id}</code>
                  </div>
                  {status !== 'revoked' ? (
                    <div className="machine-card-actions">
                      <button className="btn btn-ghost btn-sm" onClick={() => openEdit(identity)}>
                        <Pencil size={12} />
                        Edit
                      </button>
                      <button
                        className="btn btn-ghost btn-sm"
                        onClick={() => {
                          setCredentialIdentity(identity);
                          setNewCredentialName('default');
                          setNewCredentialExpiry('');
                          setCredentialActionError(null);
                        }}
                      >
                        <KeyRound size={12} />
                        Add credential
                      </button>
                      <button className="btn btn-ghost btn-sm" onClick={() => openRotate(identity)}>
                        <RotateCw size={12} />
                        Rotate
                      </button>
                      <button
                        className="btn btn-ghost btn-sm"
                        onClick={() => void handleIdentityStatus(identity, identity.disabled_at ? 'enable' : 'disable')}
                        disabled={statusActionId === identity.id}
                      >
                        {identity.disabled_at ? <ShieldCheck size={12} /> : <ShieldOff size={12} />}
                        {identity.disabled_at ? 'Enable' : 'Disable'}
                      </button>
                      {status === 'locked' ? (
                        <button className="btn btn-ghost btn-sm" onClick={() => void handleIdentityStatus(identity, 'unlock')}>
                          <LockOpen size={12} /> Unlock
                        </button>
                      ) : null}
                      <button className="btn btn-ghost btn-sm" onClick={() => void openHistory(identity)}>
                        <History size={12} /> History
                      </button>
                      <button
                        className="btn btn-ghost btn-sm btn-danger-ghost"
                        onClick={() => {
                          setRevokeError(null);
                          setIdentityPendingRevoke(identity);
                        }}
                      >
                        <ShieldOff size={12} />
                        Revoke
                      </button>
                    </div>
                  ) : null}
                </div>

                <dl className="machine-identity-details">
                  <div>
                    <dt>Scope</dt>
                    <dd>{identity.organization_id ? 'Organization' : 'Project'}</dd>
                  </div>
                  <div>
                    <dt>Environment</dt>
                    <dd><span className="badge badge-neutral">{environmentName}</span></dd>
                  </div>
                  <div>
                    <dt>Action</dt>
                    <dd className="mono">{identity.allowed_actions.join(', ')}</dd>
                  </div>
                  <div>
                    <dt>Key scope</dt>
                    <dd className="mono machine-scope-summary" title={keyScope}>{keyScope}</dd>
                  </div>
                  <div>
                    <dt>Token lifetime</dt>
                    <dd>{identity.access_token_ttl_seconds.toLocaleString()} seconds</dd>
                  </div>
                  <div>
                    <dt>Credential expiry</dt>
                    <dd>
                      {identity.credential_expires_at
                        ? formatDate(identity.credential_expires_at)
                        : 'No expiry'}
                    </dd>
                  </div>
                  <div>
                    <dt>Trusted networks</dt>
                    <dd className="mono">
                      {identity.trusted_cidrs.length ? identity.trusted_cidrs.join(', ') : 'Any IP'}
                    </dd>
                  </div>
                  <div>
                    <dt>Last authenticated</dt>
                    <dd title={identity.last_authenticated_at ?? undefined}>
                      {formatActivityTime(identity.last_authenticated_at)}
                    </dd>
                  </div>
                  <div>
                    <dt>Last used</dt>
                    <dd title={identity.last_used_at ?? undefined}>
                      {formatActivityTime(identity.last_used_at)}
                    </dd>
                  </div>
                </dl>
                <div className="machine-credentials-list">
                  <strong>Credentials ({identity.credentials.length})</strong>
                  {identity.credentials.map((item) => (
                    <div className="machine-credential-row" key={item.id}>
                      <span><code>{item.client_id}</code> · {item.name} · v{item.version}</span>
                      <span>
                        {item.revoked_at ? 'Revoked' : item.overlap_expires_at ? `Overlap until ${formatDate(item.overlap_expires_at)}` : 'Active'}
                        {!item.revoked_at ? (
                          <>
                            <button className="btn btn-ghost btn-sm" onClick={() => openRotate(identity, item)}>Rotate</button>
                            <button
                              className="btn btn-ghost btn-sm btn-danger-ghost"
                              disabled={statusActionId === item.id}
                              onClick={() => void handleRevokeCredential(identity, item)}
                            >Revoke</button>
                          </>
                        ) : null}
                      </span>
                    </div>
                  ))}
                </div>
                <div className="machine-identity-footer">
                  <span>Credential version {identity.credential_version}</span>
                  <span>Created {formatDate(identity.created_at)}</span>
                </div>
              </article>
            );
          })}
        </div>
      )}

      <Modal
        isOpen={showCreate || Boolean(editingIdentity)}
        onClose={closeForm}
        title={editingIdentity ? `Edit ${editingIdentity.name}` : 'Create Machine Identity'}
        initialFocusRef={nameInputRef}
        size="wide"
        footer={
          <>
            <button
              type="button"
              className="btn btn-secondary"
              onClick={closeForm}
              disabled={isSaving}
            >
              Cancel
            </button>
            <button
              type="button"
              className="btn btn-primary"
              onClick={() => void handleSave()}
              disabled={isSaving}
            >
              {isSaving ? 'Saving...' : editingIdentity ? 'Save Changes' : 'Create Identity'}
            </button>
          </>
        }
      >
        <IdentityFormFields
          state={form}
          environments={environments}
          disabled={isSaving}
          allowOrganizationScope={Boolean(currentProject.organization_id)}
          editing={Boolean(editingIdentity)}
          onChange={setForm}
          nameInputRef={nameInputRef}
        />
        {formError ? <p className="env-form-error" role="alert">{formError}</p> : null}
      </Modal>

      <Modal
        isOpen={Boolean(rotatingIdentity)}
        onClose={() => {
          if (!isRotating) {
            setRotatingIdentity(null);
            setRotatingCredential(null);
            setRotationError(null);
          }
        }}
        title={rotatingIdentity ? `Rotate ${rotatingIdentity.name}` : 'Rotate client secret'}
        footer={
          <>
            <button
              type="button"
              className="btn btn-secondary"
              onClick={() => setRotatingIdentity(null)}
              disabled={isRotating}
            >
              Cancel
            </button>
            <button
              type="button"
              className="btn btn-primary"
              onClick={() => void handleRotate()}
              disabled={isRotating}
            >
              <RotateCw size={14} />
              {isRotating ? 'Rotating...' : 'Rotate Secret'}
            </button>
          </>
        }
      >
        <div className="token-created-warning">
          <RotateCw size={18} />
          <div>
            <strong>Rotate with a controlled overlap window</strong>
            <p>Set overlap to 0 for immediate revocation. The replacement secret is shown once.</p>
          </div>
        </div>
        <div className="form-group">
          <label htmlFor="machine-rotation-overlap">Old credential overlap (seconds)</label>
          <input
            id="machine-rotation-overlap"
            className="input mono"
            type="number"
            min="0"
            max="604800"
            value={rotationOverlapSeconds}
            onChange={(event) => setRotationOverlapSeconds(event.target.value)}
            disabled={isRotating}
          />
          <p className="form-helper">Use a short overlap to deploy the replacement without downtime.</p>
        </div>
        <div className="form-group">
          <label htmlFor="machine-rotation-expiry">New credential expiry</label>
          <input
            id="machine-rotation-expiry"
            className="input"
            type="datetime-local"
            value={rotationExpiry}
            onChange={(event) => setRotationExpiry(event.target.value)}
            disabled={isRotating}
          />
          <p className="form-helper">Leave empty for no automatic expiry.</p>
        </div>
        {rotationError ? <p className="env-form-error" role="alert">{rotationError}</p> : null}
      </Modal>

      <Modal
        isOpen={Boolean(credentialIdentity)}
        onClose={() => { if (!isCredentialActionBusy) setCredentialIdentity(null); }}
        title={credentialIdentity ? `Add credential to ${credentialIdentity.name}` : 'Add credential'}
        footer={
          <>
            <button
              type="button"
              className="btn btn-secondary"
              onClick={() => setCredentialIdentity(null)}
              disabled={isCredentialActionBusy}
            >
              Cancel
            </button>
            <button
              type="button"
              className="btn btn-primary"
              onClick={() => void handleCreateCredential()}
              disabled={isCredentialActionBusy}
            >
              {isCredentialActionBusy ? 'Creating...' : 'Create Credential'}
            </button>
          </>
        }
      >
        <div className="form-group">
          <label htmlFor="machine-credential-name">Credential name</label>
          <input id="machine-credential-name" className="input" value={newCredentialName} onChange={(event) => setNewCredentialName(event.target.value)} disabled={isCredentialActionBusy} />
          <p className="form-helper">Use names such as blue, green, vercel, or local-development.</p>
        </div>
        <div className="form-group">
          <label htmlFor="machine-additional-credential-expiry">Credential expiry</label>
          <input id="machine-additional-credential-expiry" className="input" type="datetime-local" value={newCredentialExpiry} onChange={(event) => setNewCredentialExpiry(event.target.value)} disabled={isCredentialActionBusy} />
        </div>
        {credentialActionError ? <p className="env-form-error" role="alert">{credentialActionError}</p> : null}
      </Modal>

      <Modal
        isOpen={Boolean(historyIdentity)}
        onClose={() => setHistoryIdentity(null)}
        title={historyIdentity ? `${historyIdentity.name} authentication history` : 'Authentication history'}
        size="wide"
      >
        {isHistoryLoading ? <SectionLoader label="Loading authentication history" /> : null}
        {historyError ? <p className="env-form-error" role="alert">{historyError}</p> : null}
        {!isHistoryLoading && !historyError && authHistory.length === 0 ? <p>No authentication attempts recorded yet.</p> : null}
        {authHistory.length ? (
          <div className="machine-auth-history">
            {authHistory.map((event) => (
              <div className="machine-auth-event" key={event.id}>
                <span className={`badge ${event.success ? 'badge-success' : 'badge-danger'}`}>{event.success ? 'Success' : 'Failed'}</span>
                <code>{event.client_id}</code>
                <span>{event.reason.replace(/_/g, ' ')}</span>
                <span>{event.client_ip ?? 'Unknown IP'}</span>
                <time dateTime={event.created_at}>{formatDate(event.created_at)}</time>
              </div>
            ))}
          </div>
        ) : null}
      </Modal>

      <CredentialModal
        credential={credential}
        title={credentialTitle}
        onClose={() => setCredential(null)}
      />

      <ConfirmDialog
        isOpen={Boolean(identityPendingRevoke)}
        title="Revoke Machine Identity"
        description={
          identityPendingRevoke
            ? `Revoke “${identityPendingRevoke.name}”? Its client secret and all issued access tokens will stop working immediately.`
            : ''
        }
        errorMessage={revokeError}
        confirmLabel="Revoke Identity"
        onConfirm={() => void handleRevoke()}
        onClose={() => {
          if (!isRevoking) {
            setIdentityPendingRevoke(null);
            setRevokeError(null);
          }
        }}
        isBusy={isRevoking}
      />
    </div>
  );
}
