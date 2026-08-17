import { useEffect, useMemo, useState } from 'react';
import { Plus, Trash2 } from 'lucide-react';
import { useOutletContext } from 'react-router-dom';
import ConfirmDialog from '../components/ConfirmDialog';
import SectionLoader from '../components/SectionLoader';
import { useAuth } from '../auth/useAuth';
import {
  ApiError,
  deleteProviderCredential,
  isAbortError,
  listProviderCredentials,
  upsertProviderCredential,
} from '../lib/api';
import { formatRelativeTime } from '../lib/format';
import type { Environment, Project, ProviderCredential, ProviderName } from '../types/api';

interface OutletContextType {
  currentProject: Project;
  environments: Environment[];
  currentEnv: string;
}

const PROVIDERS: { id: ProviderName; label: string; hint: string }[] = [
  { id: 'openai', label: 'OpenAI', hint: 'Injected as Authorization: Bearer for /openai requests.' },
  { id: 'anthropic', label: 'Anthropic', hint: 'Injected as x-api-key for /anthropic requests.' },
  { id: 'github', label: 'GitHub', hint: 'Injected as Authorization: Bearer for /github requests.' },
];

export default function ProviderKeysPage() {
  const { currentProject, environments, currentEnv } = useOutletContext<OutletContextType>();
  const { accessToken } = useAuth();
  const canManage = currentProject.role === 'owner' || currentProject.can_push_pull_secrets;
  const defaultEnvId =
    currentEnv !== 'all' ? environments.find((env) => env.name === currentEnv)?.id : environments[0]?.id;

  const [environmentId, setEnvironmentId] = useState(defaultEnvId ?? '');
  const [credentials, setCredentials] = useState<ProviderCredential[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [savingProvider, setSavingProvider] = useState<ProviderName | null>(null);
  const [secretByProvider, setSecretByProvider] = useState<Partial<Record<ProviderName, string>>>({});
  const [pendingDelete, setPendingDelete] = useState<ProviderName | null>(null);
  const [isDeleting, setIsDeleting] = useState(false);

  useEffect(() => {
    if (environmentId || !environments.length) {
      return;
    }
    setEnvironmentId(defaultEnvId ?? environments[0].id);
  }, [defaultEnvId, environmentId, environments]);

  useEffect(() => {
    if (!accessToken || !environmentId) {
      return undefined;
    }
    const controller = new AbortController();
    setIsLoading(true);
    setError(null);
    listProviderCredentials(currentProject.id, environmentId, accessToken, { signal: controller.signal })
      .then((response) => {
        setCredentials(response.items);
      })
      .catch((loadError) => {
        if (isAbortError(loadError)) {
          return;
        }
        setError(loadError instanceof ApiError ? loadError.message : 'Could not load provider keys.');
      })
      .finally(() => {
        if (!controller.signal.aborted) {
          setIsLoading(false);
        }
      });
    return () => controller.abort();
  }, [accessToken, currentProject.id, environmentId]);

  const byProvider = useMemo(
    () => new Map(credentials.map((item) => [item.provider, item])),
    [credentials]
  );

  const handleSave = async (provider: ProviderName) => {
    const secret = (secretByProvider[provider] ?? '').trim();
    if (!secret || !accessToken || !environmentId) {
      return;
    }
    setSavingProvider(provider);
    setError(null);
    try {
      const saved = await upsertProviderCredential(currentProject.id, environmentId, accessToken, {
        provider,
        secret,
      });
      setCredentials((current) => {
        const next = current.filter((item) => item.provider !== provider);
        next.push(saved);
        return next.sort((left, right) => left.provider.localeCompare(right.provider));
      });
      setSecretByProvider((current) => ({ ...current, [provider]: '' }));
    } catch (saveError) {
      setError(saveError instanceof ApiError ? saveError.message : 'Could not save that provider key.');
    } finally {
      setSavingProvider(null);
    }
  };

  const handleDelete = async () => {
    if (!pendingDelete || !accessToken || !environmentId) {
      return;
    }
    setIsDeleting(true);
    setError(null);
    try {
      await deleteProviderCredential(currentProject.id, environmentId, pendingDelete, accessToken);
      setCredentials((current) => current.filter((item) => item.provider !== pendingDelete));
      setPendingDelete(null);
    } catch (deleteError) {
      setError(deleteError instanceof ApiError ? deleteError.message : 'Could not delete that provider key.');
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
            Store OpenAI, Anthropic, and GitHub keys here. Agents authenticate with a machine identity;
            the proxy injects the real key. Never put these values in proxy/.env.
          </p>
        </div>
        <div className="page-header-actions">
          <select
            className="input select"
            value={environmentId}
            onChange={(event) => setEnvironmentId(event.target.value)}
            aria-label="Environment"
          >
            {environments.map((environment) => (
              <option key={environment.id} value={environment.id}>
                {environment.name}
              </option>
            ))}
          </select>
        </div>
      </div>

      {error && <p className="env-form-error" role="alert">{error}</p>}
      {!canManage && (
        <p className="form-helper">You can view which keys are configured. Saving or deleting requires secret management access.</p>
      )}

      {isLoading ? (
        <SectionLoader label="Loading provider keys" />
      ) : (
        <div className="provider-key-grid">
          {PROVIDERS.map((provider) => {
            const existing = byProvider.get(provider.id);
            return (
              <div className="card provider-key-card" key={provider.id}>
                <div className="provider-key-header">
                  <div>
                    <h3>{provider.label}</h3>
                    <p>{provider.hint}</p>
                  </div>
                  {existing ? (
                    <span className="badge badge-success">Configured · …{existing.key_last4}</span>
                  ) : (
                    <span className="badge">Not configured</span>
                  )}
                </div>
                {existing && (
                  <p className="form-helper">
                    Last updated {formatRelativeTime(existing.updated_at)}
                  </p>
                )}
                {canManage && (
                  <>
                    <label className="form-group">
                      <span>{existing ? 'Replace key' : 'API key'}</span>
                      <input
                        className="input"
                        type="password"
                        autoComplete="off"
                        placeholder={existing ? 'Paste a new key to rotate' : 'Paste the provider API key'}
                        value={secretByProvider[provider.id] ?? ''}
                        onChange={(event) =>
                          setSecretByProvider((current) => ({
                            ...current,
                            [provider.id]: event.target.value,
                          }))
                        }
                      />
                    </label>
                    <div className="provider-key-actions">
                      <button
                        type="button"
                        className="btn btn-primary"
                        disabled={!(secretByProvider[provider.id] ?? '').trim() || savingProvider === provider.id}
                        onClick={() => handleSave(provider.id)}
                      >
                        <Plus size={14} />
                        {existing ? 'Replace key' : 'Save key'}
                      </button>
                      {existing && (
                        <button
                          type="button"
                          className="btn btn-ghost btn-danger-ghost"
                          onClick={() => setPendingDelete(provider.id)}
                        >
                          <Trash2 size={14} />
                          Remove
                        </button>
                      )}
                    </div>
                  </>
                )}
              </div>
            );
          })}
        </div>
      )}

      <ConfirmDialog
        isOpen={pendingDelete !== null}
        title="Remove provider key"
        description="The proxy will stop injecting this provider key until you save a new one."
        confirmLabel="Remove key"
        tone="danger"
        isBusy={isDeleting}
        onConfirm={() => { void handleDelete(); }}
        onClose={() => {
          if (!isDeleting) {
            setPendingDelete(null);
          }
        }}
      />
    </div>
  );
}
