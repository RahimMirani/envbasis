import { FormEvent, useEffect, useMemo, useState } from 'react';
import { Navigate, useOutletContext } from 'react-router-dom';
import { KeyRound, Pencil, Plus, Trash2 } from 'lucide-react';
import ConfirmDialog from '../components/ConfirmDialog';
import Modal from '../components/Modal';
import SectionLoader from '../components/SectionLoader';
import { useAuth } from '../auth/useAuth';
import {
  deleteProviderCredential,
  isAbortError,
  listProviderCredentials,
  upsertProviderCredential,
} from '../lib/api';
import { formatRelativeTime } from '../lib/format';
import type { ProjectPageCacheApi } from '../lib/projectPageCache';
import type { Environment, Project, ProviderCredential, ProviderName } from '../types/api';

interface OutletContextType {
  currentProject: Project;
  environments: Environment[];
  currentEnv: string;
  pageCache: ProjectPageCacheApi;
}

const PROVIDERS: Array<{ id: ProviderName; label: string; hint: string }> = [
  { id: 'openai', label: 'OpenAI', hint: 'Injected for /openai requests' },
  { id: 'anthropic', label: 'Anthropic', hint: 'Injected for /anthropic requests' },
  { id: 'github', label: 'GitHub', hint: 'Injected for /github requests' },
];

function maskKey(last4: string): string {
  return `••••${last4}`;
}

export default function ProviderKeysPage() {
  const { accessToken } = useAuth();
  const { currentProject, environments, currentEnv, pageCache } = useOutletContext<OutletContextType>();
  const canManage = currentProject.can_manage_runtime_tokens;

  const selectedEnvironment = useMemo(() => {
    if (currentEnv === 'all') {
      return environments[0] ?? null;
    }
    return environments.find((environment) => environment.name === currentEnv) ?? environments[0] ?? null;
  }, [currentEnv, environments]);

  const cacheKey = selectedEnvironment
    ? `provider-keys:${currentProject.id}:${selectedEnvironment.id}`
    : null;
  const cached = cacheKey ? pageCache.get<ProviderCredential[]>(cacheKey) : null;

  const [credentials, setCredentials] = useState<ProviderCredential[]>(() => cached ?? []);
  const [isLoading, setIsLoading] = useState(!cached);
  const [error, setError] = useState<string | null>(null);
  const [editingProvider, setEditingProvider] = useState<ProviderName | null>(null);
  const [secretValue, setSecretValue] = useState('');
  const [isSaving, setIsSaving] = useState(false);
  const [pendingDelete, setPendingDelete] = useState<ProviderName | null>(null);
  const [isDeleting, setIsDeleting] = useState(false);

  useEffect(() => {
    if (!accessToken || !selectedEnvironment || !canManage) {
      return undefined;
    }

    let active = true;
    const controller = new AbortController();
    const key = `provider-keys:${currentProject.id}:${selectedEnvironment.id}`;
    const existing = pageCache.get<ProviderCredential[]>(key);
    if (existing) {
      setCredentials(existing);
      setIsLoading(false);
    } else {
      setIsLoading(true);
    }
    setError(null);

    listProviderCredentials(currentProject.id, selectedEnvironment.id, accessToken, {
      signal: controller.signal,
    })
      .then((response) => {
        if (!active) return;
        setCredentials(response.credentials);
        pageCache.set(key, response.credentials);
        setIsLoading(false);
      })
      .catch((loadError) => {
        if (!active || isAbortError(loadError) || controller.signal.aborted) return;
        setError(loadError instanceof Error ? loadError.message : 'Failed to load provider keys.');
        setIsLoading(false);
      });

    return () => {
      active = false;
      controller.abort();
    };
  }, [accessToken, canManage, currentProject.id, pageCache, selectedEnvironment]);

  if (!canManage) {
    return <Navigate to="../overview" replace />;
  }

  const byProvider = useMemo(() => {
    const map = new Map<ProviderName, ProviderCredential>();
    for (const credential of credentials) {
      map.set(credential.provider, credential);
    }
    return map;
  }, [credentials]);

  const openEdit = (provider: ProviderName) => {
    setEditingProvider(provider);
    setSecretValue('');
    setError(null);
  };

  const handleSave = async (event: FormEvent) => {
    event.preventDefault();
    if (!accessToken || !selectedEnvironment || !editingProvider) return;
    if (!secretValue.trim()) {
      setError('Paste a provider API key to save.');
      return;
    }

    setIsSaving(true);
    setError(null);
    try {
      const saved = await upsertProviderCredential(
        currentProject.id,
        selectedEnvironment.id,
        accessToken,
        { provider: editingProvider, secret: secretValue.trim() }
      );
      const next = [
        ...credentials.filter((item) => item.provider !== saved.provider),
        saved,
      ].sort((left, right) => left.provider.localeCompare(right.provider));
      setCredentials(next);
      pageCache.set(`provider-keys:${currentProject.id}:${selectedEnvironment.id}`, next);
      setEditingProvider(null);
      setSecretValue('');
    } catch (saveError) {
      setError(saveError instanceof Error ? saveError.message : 'Failed to save provider key.');
    } finally {
      setIsSaving(false);
    }
  };

  const handleDelete = async () => {
    if (!accessToken || !selectedEnvironment || !pendingDelete) return;
    setIsDeleting(true);
    setError(null);
    try {
      await deleteProviderCredential(
        currentProject.id,
        selectedEnvironment.id,
        pendingDelete,
        accessToken
      );
      const next = credentials.filter((item) => item.provider !== pendingDelete);
      setCredentials(next);
      pageCache.set(`provider-keys:${currentProject.id}:${selectedEnvironment.id}`, next);
      setPendingDelete(null);
    } catch (deleteError) {
      setError(deleteError instanceof Error ? deleteError.message : 'Failed to delete provider key.');
    } finally {
      setIsDeleting(false);
    }
  };

  return (
    <div className="provider-keys-page">
      <div className="page-header">
        <div>
          <h1>Provider keys</h1>
          <p className="page-subtitle">
            Store OpenAI, Anthropic, and GitHub credentials for the agent proxy. Agents never receive
            these values — the proxy injects them at request time.
          </p>
        </div>
      </div>

      {!selectedEnvironment ? (
        <div className="card empty-state">
          <h3>Create an environment first</h3>
          <p>Provider keys are scoped to a project environment.</p>
        </div>
      ) : isLoading ? (
        <SectionLoader label="Loading provider keys" />
      ) : (
        <>
          {error ? <div className="form-error">{error}</div> : null}
          <p className="form-helper">
            Environment: <strong>{selectedEnvironment.name}</strong>. Change it from the top bar
            environment selector.
          </p>
          <div className="provider-key-grid">
            {PROVIDERS.map((provider) => {
              const configured = byProvider.get(provider.id);
              return (
                <div key={provider.id} className="card provider-key-card">
                  <div className="provider-key-header">
                    <div>
                      <h3>{provider.label}</h3>
                      <p className="form-helper">{provider.hint}</p>
                    </div>
                    <span className={`badge ${configured ? 'machine-status-active' : ''}`}>
                      {configured ? 'Configured' : 'Not set'}
                    </span>
                  </div>
                  <div className="provider-key-body">
                    {configured ? (
                      <>
                        <code className="mono">{maskKey(configured.key_last4)}</code>
                        <span className="form-helper">
                          Updated {formatRelativeTime(configured.updated_at)}
                        </span>
                      </>
                    ) : (
                      <span className="form-helper">No key stored for this environment.</span>
                    )}
                  </div>
                  <div className="provider-key-actions">
                    <button
                      type="button"
                      className="btn btn-secondary btn-sm"
                      onClick={() => openEdit(provider.id)}
                    >
                      {configured ? <Pencil size={14} /> : <Plus size={14} />}
                      {configured ? 'Rotate' : 'Add key'}
                    </button>
                    {configured ? (
                      <button
                        type="button"
                        className="btn btn-ghost btn-sm"
                        onClick={() => setPendingDelete(provider.id)}
                      >
                        <Trash2 size={14} />
                        Delete
                      </button>
                    ) : null}
                  </div>
                </div>
              );
            })}
          </div>
        </>
      )}

      <Modal
        isOpen={editingProvider !== null}
        title={
          editingProvider
            ? `${byProvider.has(editingProvider) ? 'Rotate' : 'Add'} ${
                PROVIDERS.find((item) => item.id === editingProvider)?.label ?? 'provider'
              } key`
            : 'Provider key'
        }
        onClose={() => {
          if (!isSaving) {
            setEditingProvider(null);
            setSecretValue('');
          }
        }}
        footer={
          <>
            <button
              type="button"
              className="btn btn-ghost"
              disabled={isSaving}
              onClick={() => {
                setEditingProvider(null);
                setSecretValue('');
              }}
            >
              Cancel
            </button>
            <button
              type="submit"
              form="provider-key-form"
              className="btn btn-primary"
              disabled={isSaving}
            >
              <KeyRound size={14} />
              {isSaving ? 'Saving…' : 'Save key'}
            </button>
          </>
        }
      >
        <form id="provider-key-form" onSubmit={handleSave}>
          <p className="form-helper">
            The plaintext key is stored encrypted and never shown again after save. Only the proxy can
            use it.
          </p>
          <div className="form-group">
            <label htmlFor="provider-secret">API key</label>
            <input
              id="provider-secret"
              className="input mono"
              type="password"
              autoComplete="off"
              placeholder="Paste provider API key"
              value={secretValue}
              onChange={(event) => setSecretValue(event.target.value)}
              disabled={isSaving}
            />
          </div>
          {error ? <div className="form-error">{error}</div> : null}
        </form>
      </Modal>

      <ConfirmDialog
        isOpen={pendingDelete !== null}
        title="Delete provider key?"
        description="The proxy will stop injecting this provider credential for this environment."
        confirmLabel="Delete"
        onConfirm={() => void handleDelete()}
        onClose={() => {
          if (!isDeleting) setPendingDelete(null);
        }}
        isBusy={isDeleting}
      />
    </div>
  );
}
