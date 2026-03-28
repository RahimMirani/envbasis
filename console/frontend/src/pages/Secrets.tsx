import { useEffect, useMemo, useRef, useState, ChangeEvent } from 'react';
import {
  Plus,
  Search,
  Eye,
  EyeOff,
  Copy,
  Pencil,
  Trash2,
  Upload,
  Download,
  Check,
  AlertTriangle,
} from 'lucide-react';
import { useOutletContext } from 'react-router-dom';
import CodeBlock from '../components/CodeBlock';
import Modal from '../components/Modal';
import { useAuth } from '../auth/useAuth';
import {
  createSecret,
  deleteSecret,
  listMembers,
  listSecrets,
  pullSecrets,
  pushSecrets,
  updateSecret,
  ApiError,
} from '../lib/api';
import { parseDotenv, serializeDotenv } from '../lib/dotenv';
import { formatRelativeTime } from '../lib/format';
import { getDefaultEnvironmentId } from '../lib/secrets';
import type { Project, Environment, Secret } from '../types/api';

interface OutletContextType {
  currentEnv: string;
  currentProject: Project;
  environments: Environment[];
  refreshSecretStats: () => Promise<void>;
}

interface SecretWithEnv extends Secret {
  environment: string;
  environment_id: string;
}

interface UploadResult {
  environmentName: string;
  changed: number;
  unchanged: number;
  duplicateKeys: string[];
  totalKeys: number;
}

interface ExportResult {
  environmentName: string;
  totalKeys: number;
}

function buildSecretId(secret: SecretWithEnv): string {
  return `${secret.environment_id}:${secret.key}`;
}

function getEnvironmentBadgeClass(environmentName: string): string {
  return `badge badge-env badge-env-${String(environmentName || '').toLowerCase()}`;
}

export default function SecretsPage() {
  const { currentEnv, currentProject, environments, refreshSecretStats } =
    useOutletContext<OutletContextType>();
  const { accessToken, apiConfigError, currentUser } = useAuth();
  const [search, setSearch] = useState('');
  const [secrets, setSecrets] = useState<SecretWithEnv[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [secretAccessState, setSecretAccessState] = useState<'enabled' | 'checking' | 'disabled'>(
    currentProject.role === 'owner' ? 'enabled' : 'checking'
  );
  const [revealedIds, setRevealedIds] = useState<Set<string>>(new Set());
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const [showSecretModal, setShowSecretModal] = useState(false);
  const [showUploadModal, setShowUploadModal] = useState(false);
  const [showExportModal, setShowExportModal] = useState(false);
  const [modalMode, setModalMode] = useState<'create' | 'edit'>('create');
  const [secretKey, setSecretKey] = useState('');
  const [secretValue, setSecretValue] = useState('');
  const [secretEnvironmentId, setSecretEnvironmentId] = useState('');
  const [uploadEnvironmentId, setUploadEnvironmentId] = useState('');
  const [uploadContent, setUploadContent] = useState('');
  const [uploadFilename, setUploadFilename] = useState('');
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [uploadResult, setUploadResult] = useState<UploadResult | null>(null);
  const [exportEnvironmentId, setExportEnvironmentId] = useState('');
  const [exportError, setExportError] = useState<string | null>(null);
  const [exportResult, setExportResult] = useState<ExportResult | null>(null);
  const [mutationError, setMutationError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [isExporting, setIsExporting] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const visibleEnvironments = useMemo(() => {
    if (currentEnv === 'all') {
      return environments;
    }

    return environments.filter((environment) => environment.name === currentEnv);
  }, [currentEnv, environments]);

  useEffect(() => {
    if (!accessToken || apiConfigError) {
      return undefined;
    }

    if (currentProject.role === 'owner') {
      setSecretAccessState('enabled');
      return undefined;
    }

    if (!currentUser?.email) {
      setSecretAccessState('checking');
      return undefined;
    }

    let isActive = true;
    const controller = new AbortController();
    setSecretAccessState('checking');

    async function loadSecretAccess() {
      try {
        const members = await listMembers(currentProject.id, accessToken!, {
          signal: controller.signal,
        });

        if (!isActive) {
          return;
        }

        const membership = members.find(
          (member) =>
            String(member.email || '').toLowerCase() ===
            String(currentUser?.email || '').toLowerCase()
        );

        setSecretAccessState(
          membership && membership.can_push_pull_secrets === false ? 'disabled' : 'enabled'
        );
      } catch {
        if (isActive && !controller.signal.aborted) {
          setSecretAccessState('enabled');
        }
      }
    }

    void loadSecretAccess();

    return () => {
      isActive = false;
      controller.abort();
    };
  }, [accessToken, apiConfigError, currentProject.id, currentProject.role, currentUser?.email]);

  useEffect(() => {
    if (!accessToken) {
      return undefined;
    }

    if (apiConfigError) {
      setError(apiConfigError);
      setIsLoading(false);
      return undefined;
    }

    if (secretAccessState === 'checking') {
      setIsLoading(true);
      return undefined;
    }

    if (secretAccessState === 'disabled') {
      setSecrets([]);
      setError(null);
      setIsLoading(false);
      return undefined;
    }

    if (visibleEnvironments.length === 0) {
      setSecrets([]);
      setError(null);
      setIsLoading(false);
      return undefined;
    }

    let isActive = true;
    const controller = new AbortController();

    async function loadSecrets() {
      setIsLoading(true);
      setError(null);

      try {
        const responses = await Promise.all(
          visibleEnvironments.map((environment) =>
            listSecrets(currentProject.id, environment.id, accessToken!, {
              signal: controller.signal,
            }).then((response) => ({
              environment,
              response,
            }))
          )
        );

        if (!isActive) {
          return;
        }

        const nextSecrets: SecretWithEnv[] = responses
          .flatMap(({ environment, response }) =>
            response.secrets.map((secret) => ({
              ...secret,
              environment: environment.name,
              environment_id: environment.id,
            }))
          )
          .sort((left, right) => {
            const keyComparison = left.key.localeCompare(right.key);
            if (keyComparison !== 0) {
              return keyComparison;
            }

            return left.environment.localeCompare(right.environment);
          });

        setSecrets(nextSecrets);
      } catch (loadError) {
        if (!isActive || controller.signal.aborted) {
          return;
        }

        const apiError = loadError as ApiError;
        if (apiError.status === 403) {
          setSecretAccessState('disabled');
          setError(null);
          setSecrets([]);
        } else {
          setError(apiError.message || 'Failed to load secrets.');
          setSecrets([]);
        }
      } finally {
        if (isActive) {
          setIsLoading(false);
        }
      }
    }

    void loadSecrets();

    return () => {
      isActive = false;
      controller.abort();
    };
  }, [accessToken, apiConfigError, currentProject.id, secretAccessState, visibleEnvironments]);

  const filteredSecrets = secrets.filter((secret) =>
    secret.key.toLowerCase().includes(search.toLowerCase())
  );

  const defaultEnvironmentId = getDefaultEnvironmentId(currentEnv, environments);
  const canUseSecrets = secretAccessState === 'enabled';
  const isSecretAccessDenied = secretAccessState === 'disabled';
  const cliEnvironmentName =
    currentEnv === 'all' ? environments[0]?.name || 'dev' : currentEnv;

  const toggleReveal = (id: string) => {
    setRevealedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const handleCopy = (value: string, id: string) => {
    navigator.clipboard.writeText(value);
    setCopiedId(id);
    setTimeout(() => setCopiedId(null), 2000);
  };

  const openCreateModal = () => {
    setModalMode('create');
    setSecretKey('');
    setSecretValue('');
    setSecretEnvironmentId(defaultEnvironmentId);
    setMutationError(null);
    setShowSecretModal(true);
  };

  const openUploadModal = () => {
    setUploadEnvironmentId(defaultEnvironmentId);
    setUploadContent('');
    setUploadFilename('');
    setUploadError(null);
    setShowUploadModal(true);
    if (fileInputRef.current) {
      fileInputRef.current.value = '';
    }
  };

  const openExportModal = () => {
    setExportEnvironmentId(defaultEnvironmentId);
    setExportError(null);
    setShowExportModal(true);
  };

  const openEditModal = (secret: SecretWithEnv) => {
    setModalMode('edit');
    setSecretKey(secret.key);
    setSecretValue(secret.value);
    setSecretEnvironmentId(secret.environment_id);
    setMutationError(null);
    setShowSecretModal(true);
  };

  const closeSecretModal = () => {
    if (isSubmitting) {
      return;
    }

    setShowSecretModal(false);
    setMutationError(null);
  };

  const closeUploadModal = () => {
    if (isUploading) {
      return;
    }

    setShowUploadModal(false);
    setUploadError(null);
    setUploadContent('');
    setUploadFilename('');
    setUploadEnvironmentId(defaultEnvironmentId);
    if (fileInputRef.current) {
      fileInputRef.current.value = '';
    }
  };

  const closeExportModal = () => {
    if (isExporting) {
      return;
    }

    setShowExportModal(false);
    setExportError(null);
  };

  const reloadSecrets = async () => {
    if (!accessToken || visibleEnvironments.length === 0) {
      setSecrets([]);
      return;
    }

    const responses = await Promise.all(
      visibleEnvironments.map((environment) =>
        listSecrets(currentProject.id, environment.id, accessToken).then((response) => ({
          environment,
          response,
        }))
      )
    );

    const nextSecrets: SecretWithEnv[] = responses
      .flatMap(({ environment, response }) =>
        response.secrets.map((secret) => ({
          ...secret,
          environment: environment.name,
          environment_id: environment.id,
        }))
      )
      .sort((left, right) => {
        const keyComparison = left.key.localeCompare(right.key);
        if (keyComparison !== 0) {
          return keyComparison;
        }

        return left.environment.localeCompare(right.environment);
      });

    setSecrets(nextSecrets);
  };

  const handleSaveSecret = async () => {
    const trimmedKey = secretKey.trim().toUpperCase();

    if (!secretEnvironmentId) {
      setMutationError('Select an environment.');
      return;
    }

    if (!trimmedKey) {
      setMutationError('Secret key is required.');
      return;
    }

    setIsSubmitting(true);
    setMutationError(null);

    try {
      if (modalMode === 'create') {
        await createSecret(currentProject.id, secretEnvironmentId, accessToken!, {
          key: trimmedKey,
          value: secretValue,
        });
      } else {
        await updateSecret(currentProject.id, secretEnvironmentId, trimmedKey, accessToken!, {
          value: secretValue,
        });
      }

      await reloadSecrets();
      try {
        await refreshSecretStats();
      } catch {
        // Keep the secret table fresh even if the metadata refresh fails.
      }
      setShowSecretModal(false);
      setMutationError(null);
    } catch (saveError) {
      setMutationError((saveError as Error).message || 'Failed to save secret.');
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleDeleteSecret = async (secret: SecretWithEnv) => {
    if (!window.confirm(`Delete secret "${secret.key}" from ${secret.environment}?`)) {
      return;
    }

    setError(null);

    try {
      await deleteSecret(currentProject.id, secret.environment_id, secret.key, accessToken!);
      setRevealedIds((current) => {
        const next = new Set(current);
        next.delete(buildSecretId(secret));
        return next;
      });
      await reloadSecrets();
      try {
        await refreshSecretStats();
      } catch {
        // Keep the secret table fresh even if the metadata refresh fails.
      }
    } catch (deleteError) {
      setError((deleteError as Error).message || 'Failed to delete secret.');
    }
  };

  const handleUploadFileChange = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) {
      return;
    }

    try {
      const text = await file.text();
      setUploadContent(text);
      setUploadFilename(file.name);
      setUploadError(null);
    } catch {
      setUploadError('Failed to read the selected file.');
      setUploadFilename('');
    }
  };

  const handleUploadSecrets = async () => {
    if (!uploadEnvironmentId) {
      setUploadError('Select an environment.');
      return;
    }

    let parsedSecrets: Record<string, string>;
    let duplicateKeys: string[];
    let totalKeys: number;

    try {
      const parsed = parseDotenv(uploadContent);
      parsedSecrets = parsed.secrets;
      duplicateKeys = parsed.duplicateKeys;
      totalKeys = parsed.totalKeys;
    } catch (parseError) {
      setUploadError((parseError as Error).message || 'Failed to parse .env contents.');
      return;
    }

    if (totalKeys === 0) {
      setUploadError('No secrets were found in the provided .env contents.');
      return;
    }

    setIsUploading(true);
    setUploadError(null);

    try {
      const response = await pushSecrets(currentProject.id, uploadEnvironmentId, accessToken!, {
        secrets: parsedSecrets,
      });

      const targetEnvironment = environments.find(
        (environment) => environment.id === uploadEnvironmentId
      );

      await reloadSecrets();
      try {
        await refreshSecretStats();
      } catch {
        // Keep the secret table fresh even if the metadata refresh fails.
      }

      setUploadResult({
        environmentName: targetEnvironment?.name || 'selected environment',
        changed: response.changed,
        unchanged: response.unchanged,
        duplicateKeys,
        totalKeys,
      });
      setShowUploadModal(false);
      setUploadContent('');
      setUploadFilename('');
      if (fileInputRef.current) {
        fileInputRef.current.value = '';
      }
    } catch (pushErrorValue) {
      setUploadError((pushErrorValue as Error).message || 'Failed to import .env secrets.');
    } finally {
      setIsUploading(false);
    }
  };

  const handleExportSecrets = async () => {
    if (!exportEnvironmentId) {
      setExportError('Select an environment.');
      return;
    }

    setIsExporting(true);
    setExportError(null);

    try {
      const response = await pullSecrets(currentProject.id, exportEnvironmentId, accessToken!);
      const targetEnvironment = environments.find(
        (environment) => environment.id === exportEnvironmentId
      );
      const environmentName = targetEnvironment?.name || 'environment';
      const dotenvContent = serializeDotenv(response.secrets);
      const blob = new Blob([dotenvContent ? `${dotenvContent}\n` : ''], {
        type: 'text/plain;charset=utf-8',
      });
      const url = window.URL.createObjectURL(blob);
      const anchor = document.createElement('a');
      const safeProjectName =
        currentProject.name.replace(/[^a-z0-9_-]+/gi, '-').replace(/^-+|-+$/g, '') || 'project';
      const safeEnvironmentName =
        environmentName.replace(/[^a-z0-9_-]+/gi, '-').replace(/^-+|-+$/g, '') || 'env';

      anchor.href = url;
      anchor.download = `${safeProjectName}.${safeEnvironmentName}.env`;
      document.body.appendChild(anchor);
      anchor.click();
      document.body.removeChild(anchor);
      window.URL.revokeObjectURL(url);

      setExportResult({
        environmentName,
        totalKeys: Object.keys(response.secrets || {}).length,
      });
      setShowExportModal(false);
    } catch (pullErrorValue) {
      setExportError((pullErrorValue as Error).message || 'Failed to export .env secrets.');
    } finally {
      setIsExporting(false);
    }
  };

  return (
    <div className="secrets-page animate-in">
      <div className="page-header">
        <div>
          <h1 className="page-heading">Secrets</h1>
          <p className="page-subtitle">
            Manage your project's environment variables. Values are hidden by default.
          </p>
        </div>
        <div className="page-header-actions">
          <button
            className="btn btn-secondary"
            id="bulk-download-btn"
            onClick={openExportModal}
            disabled={!canUseSecrets || environments.length === 0}
          >
            <Download size={14} />
            Download .env
          </button>
          <button
            className="btn btn-secondary"
            id="bulk-upload-btn"
            onClick={openUploadModal}
            disabled={!canUseSecrets || visibleEnvironments.length === 0}
          >
            <Upload size={14} />
            Upload .env
          </button>
          <button
            className="btn btn-primary"
            onClick={openCreateModal}
            id="add-secret-btn"
            disabled={!canUseSecrets || visibleEnvironments.length === 0}
          >
            <Plus size={14} />
            Add Secret
          </button>
        </div>
      </div>

      {isSecretAccessDenied && (
        <p className="secrets-note">
          Secret values are disabled for your membership. A project owner can re-enable push/pull
          access from the Team page.
        </p>
      )}

      {error && (
        <div className="auth-status auth-status-error" role="alert">
          <span>{error}</span>
        </div>
      )}

      {uploadResult && (
        <div className="secrets-upload-result" role="status">
          <strong>
            {uploadResult.totalKeys} secret{uploadResult.totalKeys !== 1 ? 's' : ''} imported into{' '}
            {uploadResult.environmentName}.
          </strong>
          <span>
            {uploadResult.changed} changed, {uploadResult.unchanged} unchanged.
          </span>
          {uploadResult.duplicateKeys.length > 0 && (
            <span>
              {uploadResult.duplicateKeys.length} duplicate key
              {uploadResult.duplicateKeys.length !== 1 ? 's used' : ' used'} last-value wins.
            </span>
          )}
        </div>
      )}

      {exportResult && (
        <div className="secrets-upload-result" role="status">
          <strong>Downloaded {exportResult.environmentName}.env</strong>
          <span>
            {exportResult.totalKeys} secret{exportResult.totalKeys !== 1 ? 's' : ''} exported.
          </span>
        </div>
      )}

      {/* Search */}
      <div className="secrets-toolbar">
        <div className="secrets-search">
          <Search size={14} className="secrets-search-icon" />
          <input
            type="text"
            className="input secrets-search-input"
            placeholder="Search secrets..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            id="secrets-search"
          />
        </div>
        <span className="secrets-count">
          {filteredSecrets.length} secret{filteredSecrets.length !== 1 ? 's' : ''}
        </span>
      </div>

      {isSecretAccessDenied ? (
        <div className="empty-state">
          <h3>Secret access is disabled</h3>
          <p>
            You can stay in the project and view project metadata, but secret values and secret
            mutations are currently restricted for your account.
          </p>
        </div>
      ) : visibleEnvironments.length === 0 ? (
        <div className="empty-state">
          <h3>No environments available</h3>
          <p>Create an environment first before adding secrets.</p>
        </div>
      ) : isLoading ? (
        <div className="empty-state">
          <h3>Loading secrets</h3>
          <p>Fetching secrets for the selected environment scope.</p>
        </div>
      ) : filteredSecrets.length === 0 ? (
        <div className="empty-state">
          <h3>No secrets found</h3>
          <p>
            {search
              ? 'Try a different search term.'
              : currentEnv === 'all'
                ? 'Add a secret to any environment in this project.'
                : `Add a secret to ${currentEnv}.`}
          </p>
          <button className="btn btn-primary" onClick={openCreateModal}>
            <Plus size={14} />
            Add Secret
          </button>
        </div>
      ) : (
        <div className="card">
          <div className="table-wrapper">
            <table id="secrets-table">
              <thead>
                <tr>
                  <th>Key</th>
                  <th>Value</th>
                  <th>Environment</th>
                  <th>Version</th>
                  <th>Updated</th>
                  <th>By</th>
                  <th style={{ width: 140 }}>Actions</th>
                </tr>
              </thead>
              <tbody>
                {filteredSecrets.map((secret) => {
                  const secretId = buildSecretId(secret);
                  const isRevealed = revealedIds.has(secretId);
                  const isCopied = copiedId === secretId;
                  return (
                    <tr key={secretId}>
                      <td>
                        <code className="secret-key">{secret.key}</code>
                      </td>
                      <td>
                        <span
                          className={`secret-value mono ${isRevealed ? 'secret-value-revealed' : ''}`}
                        >
                          {isRevealed ? secret.value : '••••••••••••'}
                        </span>
                      </td>
                      <td>
                        <span className={getEnvironmentBadgeClass(secret.environment)}>
                          {secret.environment}
                        </span>
                      </td>
                      <td className="text-mono text-sm">v{secret.version}</td>
                      <td className="text-secondary">{formatRelativeTime(secret.updated_at)}</td>
                      <td className="text-secondary">
                        {secret.updated_by_email || 'Unknown user'}
                      </td>
                      <td>
                        <div className="secret-actions">
                          <button
                            className="btn btn-ghost btn-icon btn-sm"
                            onClick={() => toggleReveal(secretId)}
                            data-tooltip={isRevealed ? 'Hide' : 'Reveal'}
                            aria-label={isRevealed ? 'Hide secret' : 'Reveal secret'}
                          >
                            {isRevealed ? <EyeOff size={14} /> : <Eye size={14} />}
                          </button>
                          <button
                            className="btn btn-ghost btn-icon btn-sm"
                            onClick={() => handleCopy(secret.value, secretId)}
                            data-tooltip={isCopied ? 'Copied!' : 'Copy'}
                            aria-label="Copy secret value"
                          >
                            {isCopied ? (
                              <Check size={14} className="text-success" />
                            ) : (
                              <Copy size={14} />
                            )}
                          </button>
                          <button
                            className="btn btn-ghost btn-icon btn-sm"
                            onClick={() => openEditModal(secret)}
                            data-tooltip="Edit"
                            aria-label="Edit secret"
                          >
                            <Pencil size={14} />
                          </button>
                          <button
                            className="btn btn-ghost btn-icon btn-sm btn-danger-subtle"
                            onClick={() => handleDeleteSecret(secret)}
                            data-tooltip="Delete"
                            aria-label="Delete secret"
                          >
                            <Trash2 size={14} />
                          </button>
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

      {/* CLI Hint */}
      {canUseSecrets && (
        <div className="secrets-cli-hint">
          <CodeBlock
            commands={[
              { cmd: 'envbasis', args: `push --env ${cliEnvironmentName}` },
              { cmd: 'envbasis', args: `pull --env ${cliEnvironmentName}` },
            ]}
          />
        </div>
      )}

      {/* Export Modal */}
      <Modal
        isOpen={showExportModal}
        onClose={closeExportModal}
        title="Download .env"
        footer={
          <>
            <button
              className="btn btn-secondary"
              onClick={closeExportModal}
              disabled={isExporting}
            >
              Cancel
            </button>
            <button
              className="btn btn-primary"
              onClick={handleExportSecrets}
              disabled={isExporting}
            >
              <Download size={14} />
              {isExporting ? 'Downloading...' : 'Download .env'}
            </button>
          </>
        }
      >
        <div className="form-group">
          <label htmlFor="export-secret-env-input">Environment</label>
          <select
            id="export-secret-env-input"
            className="input select"
            value={exportEnvironmentId}
            onChange={(event) => setExportEnvironmentId(event.target.value)}
            disabled={currentEnv !== 'all' || isExporting}
          >
            {environments.map((environment) => (
              <option key={environment.id} value={environment.id}>
                {environment.name}
              </option>
            ))}
          </select>
        </div>
        {exportError && (
          <p className="secrets-form-error" role="alert">
            {exportError}
          </p>
        )}
        <div className="add-secret-warning">
          <AlertTriangle size={14} />
          <span>
            Downloads secret values as a plain-text `.env` file for the selected environment.
          </span>
        </div>
      </Modal>

      {/* Upload Modal */}
      <Modal
        isOpen={showUploadModal}
        onClose={closeUploadModal}
        title="Import .env"
        footer={
          <>
            <button
              className="btn btn-secondary"
              onClick={closeUploadModal}
              disabled={isUploading}
            >
              Cancel
            </button>
            <button
              className="btn btn-primary"
              onClick={handleUploadSecrets}
              disabled={isUploading}
            >
              <Upload size={14} />
              {isUploading ? 'Importing...' : 'Import Secrets'}
            </button>
          </>
        }
      >
        <div className="form-group">
          <label htmlFor="upload-secret-env-input">Environment</label>
          <select
            id="upload-secret-env-input"
            className="input select"
            value={uploadEnvironmentId}
            onChange={(event) => setUploadEnvironmentId(event.target.value)}
            disabled={currentEnv !== 'all' || isUploading}
          >
            {environments.map((environment) => (
              <option key={environment.id} value={environment.id}>
                {environment.name}
              </option>
            ))}
          </select>
        </div>
        <div className="form-group">
          <label htmlFor="upload-dotenv-file-input">Choose .env file</label>
          <input
            ref={fileInputRef}
            id="upload-dotenv-file-input"
            className="input"
            type="file"
            accept=".env,text/plain"
            onChange={(event) => {
              void handleUploadFileChange(event);
            }}
            disabled={isUploading}
          />
          <p className="secrets-upload-hint">
            {uploadFilename
              ? `Loaded ${uploadFilename}. You can still edit the contents below before importing.`
              : 'Upload a .env file or paste its contents below.'}
          </p>
        </div>
        <div className="form-group">
          <label htmlFor="upload-dotenv-content-input">.env contents</label>
          <textarea
            id="upload-dotenv-content-input"
            className="input secrets-upload-textarea mono"
            placeholder={
              'OPENAI_API_KEY=sk-...\nDATABASE_URL=postgres://...\n# Comments are ignored'
            }
            value={uploadContent}
            onChange={(event) => setUploadContent(event.target.value)}
            disabled={isUploading}
            rows={10}
          />
        </div>
        {uploadError && (
          <p className="secrets-form-error" role="alert">
            {uploadError}
          </p>
        )}
        <div className="add-secret-warning">
          <AlertTriangle size={14} />
          <span>Bulk import creates or updates secrets in one environment at a time.</span>
        </div>
      </Modal>

      {/* Secret Modal */}
      <Modal
        isOpen={showSecretModal}
        onClose={closeSecretModal}
        title={modalMode === 'create' ? 'Add Secret' : 'Edit Secret'}
        footer={
          <>
            <button
              className="btn btn-secondary"
              onClick={closeSecretModal}
              disabled={isSubmitting}
            >
              Cancel
            </button>
            <button
              className="btn btn-primary"
              onClick={handleSaveSecret}
              id="save-secret-btn"
              disabled={isSubmitting}
            >
              <Plus size={14} />
              {isSubmitting
                ? modalMode === 'create'
                  ? 'Adding...'
                  : 'Saving...'
                : modalMode === 'create'
                  ? 'Add Secret'
                  : 'Save Secret'}
            </button>
          </>
        }
      >
        <div className="form-group">
          <label htmlFor="secret-key-input">Key</label>
          <input
            id="secret-key-input"
            className="input mono"
            placeholder="e.g. OPENAI_API_KEY"
            value={secretKey}
            onChange={(e) => setSecretKey(e.target.value.toUpperCase())}
            disabled={modalMode === 'edit' || isSubmitting}
          />
        </div>
        <div className="form-group">
          <label htmlFor="secret-value-input">Value</label>
          <input
            id="secret-value-input"
            className="input mono"
            type="password"
            placeholder="Enter secret value"
            value={secretValue}
            onChange={(e) => setSecretValue(e.target.value)}
            disabled={isSubmitting}
          />
        </div>
        <div className="form-group">
          <label htmlFor="secret-env-input">Environment</label>
          <select
            id="secret-env-input"
            className="input select"
            value={secretEnvironmentId}
            onChange={(event) => setSecretEnvironmentId(event.target.value)}
            disabled={modalMode === 'edit' || currentEnv !== 'all' || isSubmitting}
          >
            {environments.map((environment) => (
              <option key={environment.id} value={environment.id}>
                {environment.name}
              </option>
            ))}
          </select>
        </div>
        {mutationError && (
          <p className="secrets-form-error" role="alert">
            {mutationError}
          </p>
        )}
        <div className="add-secret-warning">
          <AlertTriangle size={14} />
          <span>Secret values are encrypted at rest and never exposed in logs.</span>
        </div>
      </Modal>
    </div>
  );
}
