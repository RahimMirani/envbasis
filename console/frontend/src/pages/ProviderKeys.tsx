import { useEffect, useMemo, useState } from 'react';
import { Plus, RefreshCw, Trash2 } from 'lucide-react';
import { useOutletContext } from 'react-router-dom';
import ConfirmDialog from '../components/ConfirmDialog';
import Modal from '../components/Modal';
import SectionLoader from '../components/SectionLoader';
import Select, { envDotClass } from '../components/Select';
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
  { id: 'openai', label: 'OpenAI', hint: 'Sent as Authorization: Bearer on /openai requests.' },
  { id: 'anthropic', label: 'Anthropic', hint: 'Sent as x-api-key on /anthropic requests.' },
  { id: 'github', label: 'GitHub', hint: 'Sent as Authorization: Bearer on /github requests.' },
];

interface ProviderKeyRow extends ProviderCredential {
  environment_id: string;
  environment_name: string;
}

function providerLabel(provider: ProviderName): string {
  return PROVIDERS.find((item) => item.id === provider)?.label ?? provider;
}

function getEnvironmentBadgeClass(environmentName: string): string {
  return `badge badge-env badge-env-${String(environmentName || '').toLowerCase()}`;
}

export default function ProviderKeysPage() {
  const { currentProject, environments, currentEnv } = useOutletContext<OutletContextType>();
  const { accessToken } = useAuth();
  const canManage = currentProject.role === 'owner' || currentProject.can_manage_secrets;

  const [rows, setRows] = useState<ProviderKeyRow[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [reloadNonce, setReloadNonce] = useState(0);

  const filterEnvironmentId =
    currentEnv === 'all'
      ? 'all'
      : environments.find((env) => env.name === currentEnv)?.id ?? 'all';
  const [filterProvider, setFilterProvider] = useState<'all' | ProviderName>('all');

  const [showKeyModal, setShowKeyModal] = useState(false);
  const [modalMode, setModalMode] = useState<'add' | 'replace'>('add');
  const [modalProvider, setModalProvider] = useState<ProviderName>('openai');
  const [modalEnvironmentId, setModalEnvironmentId] = useState('');
  const [modalSecret, setModalSecret] = useState('');
  const [modalError, setModalError] = useState<string | null>(null);
  const [isSaving, setIsSaving] = useState(false);

  const [pendingDelete, setPendingDelete] = useState<ProviderKeyRow | null>(null);
  const [isDeleting, setIsDeleting] = useState(false);

  useEffect(() => {
    if (!accessToken || environments.length === 0) {
      setRows([]);
      setIsLoading(false);
      return undefined;
    }
    const controller = new AbortController();
    let active = true;
    setIsLoading(true);
    setError(null);
    Promise.all(
      environments.map(async (environment) => {
        const response = await listProviderCredentials(currentProject.id, environment.id, accessToken, {
          signal: controller.signal,
        });
        return response.items.map((item) => ({
          ...item,
          environment_id: environment.id,
          environment_name: environment.name,
        }));
      })
    )
      .then((groups) => {
        if (active) {
          setRows(groups.flat());
        }
      })
      .catch((loadError) => {
        if (!active || isAbortError(loadError)) {
          return;
        }
        setError(loadError instanceof ApiError ? loadError.message : 'Could not load provider keys.');
      })
      .finally(() => {
        if (active && !controller.signal.aborted) {
          setIsLoading(false);
        }
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [accessToken, currentProject.id, environments, reloadNonce]);

  const visibleRows = useMemo(
    () =>
      rows
        .filter((row) => filterEnvironmentId === 'all' || row.environment_id === filterEnvironmentId)
        .filter((row) => filterProvider === 'all' || row.provider === filterProvider)
        .sort(
          (left, right) =>
            left.environment_name.localeCompare(right.environment_name) ||
            left.provider.localeCompare(right.provider)
        ),
    [filterEnvironmentId, filterProvider, rows]
  );
  const hasActiveFilters = filterEnvironmentId !== 'all' || filterProvider !== 'all';

  const openAddModal = () => {
    setModalMode('add');
    setModalProvider('openai');
    setModalEnvironmentId(filterEnvironmentId !== 'all' ? filterEnvironmentId : environments[0]?.id ?? '');
    setModalSecret('');
    setModalError(null);
    setShowKeyModal(true);
  };

  const openReplaceModal = (row: ProviderKeyRow) => {
    setModalMode('replace');
    setModalProvider(row.provider);
    setModalEnvironmentId(row.environment_id);
    setModalSecret('');
    setModalError(null);
    setShowKeyModal(true);
  };

  const closeKeyModal = () => {
    if (isSaving) {
      return;
    }
    setShowKeyModal(false);
    setModalSecret('');
    setModalError(null);
  };

  const existingForModal = rows.find(
    (row) => row.provider === modalProvider && row.environment_id === modalEnvironmentId
  );
  const modalHint = PROVIDERS.find((provider) => provider.id === modalProvider)?.hint;

  const handleSave = async () => {
    const secret = modalSecret.trim();
    if (!modalEnvironmentId) {
      setModalError('Select an environment.');
      return;
    }
    if (!secret) {
      setModalError('Paste the provider API key.');
      return;
    }
    if (!accessToken) {
      return;
    }
    setIsSaving(true);
    setModalError(null);
    try {
      await upsertProviderCredential(currentProject.id, modalEnvironmentId, accessToken, {
        provider: modalProvider,
        secret,
      });
      setShowKeyModal(false);
      setModalSecret('');
      setReloadNonce((nonce) => nonce + 1);
    } catch (saveError) {
      setModalError(saveError instanceof ApiError ? saveError.message : 'Could not save that provider key.');
    } finally {
      setIsSaving(false);
    }
  };

  const handleDelete = async () => {
    if (!pendingDelete || !accessToken) {
      return;
    }
    setIsDeleting(true);
    setError(null);
    try {
      await deleteProviderCredential(
        currentProject.id,
        pendingDelete.environment_id,
        pendingDelete.provider,
        accessToken
      );
      setPendingDelete(null);
      setReloadNonce((nonce) => nonce + 1);
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
          <h1>Proxy secrets</h1>
          <p className="page-subtitle">
            Provider keys the proxy injects for agents. Agents authenticate with a machine identity and
            never see these values.
          </p>
        </div>
        <div className="page-header-actions">
          {canManage && (
            <button type="button" className="btn btn-primary" onClick={openAddModal} disabled={environments.length === 0}>
              <Plus size={14} />
              Add Key
            </button>
          )}
        </div>
      </div>

      {error && <p className="env-form-error" role="alert">{error}</p>}
      {!canManage && (
        <p className="form-helper">
          You can view which keys are configured. Adding, replacing, or deleting requires secret management access.
        </p>
      )}

      <div className="provider-key-filters">
        <div className="provider-env-picker">
          <span>Provider</span>
          <Select
            ariaLabel="Filter by provider"
            value={filterProvider}
            onChange={(next) => setFilterProvider(next as 'all' | ProviderName)}
            options={[
              { value: 'all', label: 'All providers' },
              ...PROVIDERS.map((provider) => ({ value: provider.id, label: provider.label })),
            ]}
          />
        </div>
      </div>

      {isLoading ? (
        <SectionLoader label="Loading provider keys" />
      ) : environments.length === 0 ? (
        <div className="empty-state">
          <h3>No environments available</h3>
          <p>Create an environment first, then add provider keys for it.</p>
        </div>
      ) : visibleRows.length === 0 ? (
        <div className="empty-state">
          <h3>{hasActiveFilters ? 'No matching keys' : 'No provider keys yet'}</h3>
          <p>
            {hasActiveFilters
              ? 'Try different filters, or add a key for this selection.'
              : 'Add an OpenAI, Anthropic, or GitHub key so the proxy can inject it for your agents.'}
          </p>
          {canManage && (
            <button type="button" className="btn btn-primary" onClick={openAddModal}>
              <Plus size={14} />
              Add Key
            </button>
          )}
        </div>
      ) : (
        <div className="card">
          <div className="table-wrapper">
            <table>
              <thead>
                <tr>
                  <th>Provider</th>
                  <th>Environment</th>
                  <th>Key</th>
                  <th>Updated</th>
                  {canManage && <th style={{ width: 110 }}>Actions</th>}
                </tr>
              </thead>
              <tbody>
                {visibleRows.map((row) => (
                  <tr key={`${row.environment_id}:${row.provider}`}>
                    <td className="provider-key-name">{providerLabel(row.provider)}</td>
                    <td>
                      <span className={getEnvironmentBadgeClass(row.environment_name)}>
                        {row.environment_name}
                      </span>
                    </td>
                    <td>
                      <span className="mono text-sm">••••••••{row.key_last4}</span>
                    </td>
                    <td className="text-secondary">{formatRelativeTime(row.updated_at)}</td>
                    {canManage && (
                      <td>
                        <div className="secret-actions">
                          <button
                            type="button"
                            className="btn btn-ghost btn-icon btn-sm"
                            onClick={() => openReplaceModal(row)}
                            data-tooltip="Replace key"
                            aria-label={`Replace ${providerLabel(row.provider)} key`}
                          >
                            <RefreshCw size={14} />
                          </button>
                          <button
                            type="button"
                            className="btn btn-ghost btn-icon btn-sm btn-danger-subtle"
                            onClick={() => setPendingDelete(row)}
                            data-tooltip="Delete"
                            aria-label={`Delete ${providerLabel(row.provider)} key`}
                          >
                            <Trash2 size={14} />
                          </button>
                        </div>
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      <Modal
        isOpen={showKeyModal}
        onClose={closeKeyModal}
        title={modalMode === 'add' ? 'Add Provider Key' : 'Replace Provider Key'}
        footer={
          <>
            <button type="button" className="btn btn-secondary" onClick={closeKeyModal} disabled={isSaving}>
              Cancel
            </button>
            <button type="button" className="btn btn-primary" onClick={handleSave} disabled={isSaving || !modalSecret.trim()}>
              {modalMode === 'add' ? <Plus size={14} /> : <RefreshCw size={14} />}
              {isSaving ? 'Saving...' : modalMode === 'add' ? 'Add Key' : 'Replace Key'}
            </button>
          </>
        }
      >
        <div className="form-group">
          <label htmlFor="provider-key-provider">Provider</label>
          <Select
            id="provider-key-provider"
            value={modalProvider}
            onChange={(next) => setModalProvider(next as ProviderName)}
            disabled={modalMode === 'replace' || isSaving}
            options={PROVIDERS.map((provider) => ({ value: provider.id, label: provider.label }))}
          />
          {modalHint && <p className="secrets-upload-hint">{modalHint}</p>}
        </div>
        <div className="form-group">
          <label htmlFor="provider-key-environment">Environment</label>
          <Select
            id="provider-key-environment"
            value={modalEnvironmentId}
            onChange={setModalEnvironmentId}
            disabled={modalMode === 'replace' || isSaving}
            placeholder="Select an environment"
            options={environments.map((environment) => ({
              value: environment.id,
              label: environment.name,
              dotClass: envDotClass(environment.name),
            }))}
          />
        </div>
        <div className="form-group">
          <label htmlFor="provider-key-secret">API key</label>
          <input
            id="provider-key-secret"
            name={`provider-key-${modalProvider}`}
            className="input mono input-secret-mask"
            type="text"
            autoComplete="off"
            autoCorrect="off"
            autoCapitalize="off"
            spellCheck={false}
            data-lpignore="true"
            data-1p-ignore="true"
            placeholder={
              existingForModal ? 'Paste a new key to replace the stored one' : 'Paste the provider API key'
            }
            value={modalSecret}
            onChange={(event) => setModalSecret(event.target.value)}
            disabled={isSaving}
          />
          {modalMode === 'add' && existingForModal && (
            <p className="secrets-upload-hint">
              A key ending in {existingForModal.key_last4} is already stored for this selection — saving will
              replace it.
            </p>
          )}
        </div>
        {modalError && (
          <p className="secrets-form-error" role="alert">
            {modalError}
          </p>
        )}
      </Modal>

      <ConfirmDialog
        isOpen={pendingDelete !== null}
        title="Remove provider key"
        description={
          pendingDelete
            ? `The proxy will stop injecting the ${providerLabel(pendingDelete.provider)} key for ${pendingDelete.environment_name} until you add a new one.`
            : ''
        }
        confirmLabel="Remove key"
        tone="danger"
        isBusy={isDeleting}
        onConfirm={() => {
          void handleDelete();
        }}
        onClose={() => {
          if (!isDeleting) {
            setPendingDelete(null);
          }
        }}
      />
    </div>
  );
}
