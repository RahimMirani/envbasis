import { useRef, useState } from 'react';
import { Plus, Activity, Clock, KeyRound, Pencil, Trash2 } from 'lucide-react';
import { useOutletContext } from 'react-router-dom';
import ConfirmDialog from '../components/ConfirmDialog';
import Modal from '../components/Modal';
import { useAuth } from '../auth/useAuth';
import { createEnvironment, renameEnvironment, deleteEnvironment } from '../lib/api';
import { formatDate, formatRelativeTime, getEnvironmentColor } from '../lib/format';
import type { Project, Environment, SecretStats } from '../types/api';

interface OutletContextType {
  currentProject: Project;
  environments: Environment[];
  canManageProject: boolean;
  onEnvironmentCreated: (env: Environment) => void;
  onEnvironmentUpdated: (env: Environment) => void;
  onEnvironmentDeleted: (envId: string) => void;
  secretStats: SecretStats | null;
  isSecretStatsLoading: boolean;
}

export default function EnvironmentsPage() {
  const {
    currentProject,
    environments,
    canManageProject,
    onEnvironmentCreated,
    onEnvironmentUpdated,
    onEnvironmentDeleted,
    secretStats,
    isSecretStatsLoading,
  } = useOutletContext<OutletContextType>();
  const { accessToken } = useAuth();

  // Create
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [createName, setCreateName] = useState('');
  const [createError, setCreateError] = useState<string | null>(null);
  const [isCreating, setIsCreating] = useState(false);

  // Rename
  const [envPendingRename, setEnvPendingRename] = useState<Environment | null>(null);
  const [renameName, setRenameName] = useState('');
  const [renameError, setRenameError] = useState<string | null>(null);
  const [isRenaming, setIsRenaming] = useState(false);
  const renameInputRef = useRef<HTMLInputElement>(null);

  // Delete
  const [envPendingDelete, setEnvPendingDelete] = useState<Environment | null>(null);
  const [isDeleting, setIsDeleting] = useState(false);

  const secretStatsByEnvironmentId = new Map(
    (secretStats?.environments || []).map((item) => [item.environment_id, item])
  );

  // --- Create ---
  const openCreateModal = () => {
    setShowCreateModal(true);
    setCreateName('');
    setCreateError(null);
  };

  const closeCreateModal = () => {
    if (isCreating) return;
    setShowCreateModal(false);
    setCreateName('');
    setCreateError(null);
  };

  const handleCreate = async () => {
    const trimmed = createName.trim();
    if (!trimmed) { setCreateError('Environment name is required.'); return; }
    setIsCreating(true);
    setCreateError(null);
    try {
      const environment = await createEnvironment(currentProject.id, accessToken!, { name: trimmed });
      onEnvironmentCreated(environment);
      setShowCreateModal(false);
      setCreateName('');
    } catch (err) {
      setCreateError((err as Error).message || 'Failed to create environment.');
    } finally {
      setIsCreating(false);
    }
  };

  // --- Rename ---
  const openRenameModal = (env: Environment) => {
    setEnvPendingRename(env);
    setRenameName(env.name);
    setRenameError(null);
  };

  const closeRenameModal = () => {
    if (isRenaming) return;
    setEnvPendingRename(null);
    setRenameName('');
    setRenameError(null);
  };

  const handleRename = async () => {
    if (!envPendingRename) return;
    const trimmed = renameName.trim();
    if (!trimmed) { setRenameError('Environment name is required.'); return; }
    if (trimmed === envPendingRename.name) { closeRenameModal(); return; }
    setIsRenaming(true);
    setRenameError(null);
    try {
      const updated = await renameEnvironment(currentProject.id, envPendingRename.id, accessToken!, { name: trimmed });
      onEnvironmentUpdated(updated);
      setEnvPendingRename(null);
    } catch (err) {
      setRenameError((err as Error).message || 'Failed to rename environment.');
    } finally {
      setIsRenaming(false);
    }
  };

  // --- Delete ---
  const handleDelete = async () => {
    if (!envPendingDelete) return;
    setIsDeleting(true);
    try {
      await deleteEnvironment(currentProject.id, envPendingDelete.id, accessToken!);
      onEnvironmentDeleted(envPendingDelete.id);
      setEnvPendingDelete(null);
    } catch {
      // keep dialog open so user sees the error isn't swallowed
    } finally {
      setIsDeleting(false);
    }
  };

  return (
    <div className="environments-page animate-in">
      <div className="page-header">
        <div>
          <h1 className="page-heading">Environments</h1>
          <p className="page-subtitle">
            Separate your secrets by environment. Each environment has its own set of secrets and
            runtime tokens.
          </p>
        </div>
        <div className="page-header-actions">
          <button
            className="btn btn-primary"
            id="create-env-btn"
            onClick={openCreateModal}
            disabled={!canManageProject}
          >
            <Plus size={14} />
            Create Environment
          </button>
        </div>
      </div>

      {!canManageProject && (
        <p className="env-note">Only owners can manage environments for this project.</p>
      )}

      {environments.length === 0 ? (
        <div className="empty-state">
          <h3>No environments yet</h3>
          <p>Create the first environment for {currentProject.name}.</p>
          {canManageProject && (
            <button className="btn btn-primary" onClick={openCreateModal}>
              <Plus size={14} />
              Create Environment
            </button>
          )}
        </div>
      ) : (
        <div className="env-grid stagger-in">
          {environments.map((env) => {
            const stats = secretStatsByEnvironmentId.get(env.id);
            const secretCount = stats?.secret_count ?? 0;
            const lastUpdatedLabel = isSecretStatsLoading
              ? 'Loading...'
              : stats?.last_updated_at
                ? formatRelativeTime(stats.last_updated_at)
                : 'No active secrets';
            const lastActivityLabel = isSecretStatsLoading
              ? 'Loading...'
              : stats?.last_activity_at
                ? formatRelativeTime(stats.last_activity_at)
                : 'No secret activity';

            return (
              <div className="card env-card" key={env.id} id={`env-${env.name}`}>
                <div className="env-card-header">
                  <div
                    className="env-card-dot"
                    style={{ background: getEnvironmentColor(env.name) }}
                  />
                  <h3 className="env-card-name mono">{env.name}</h3>
                  {canManageProject && (
                    <div className="env-card-actions">
                      <button
                        className="btn btn-ghost btn-icon-sm"
                        title="Rename environment"
                        onClick={() => openRenameModal(env)}
                      >
                        <Pencil size={13} />
                      </button>
                      <button
                        className="btn btn-ghost btn-icon-sm btn-danger-ghost"
                        title="Delete environment"
                        onClick={() => setEnvPendingDelete(env)}
                      >
                        <Trash2 size={13} />
                      </button>
                    </div>
                  )}
                </div>

                <div className="env-card-meta">
                  <div className="env-stat">
                    <KeyRound size={14} />
                    <div>
                      <span className="env-stat-value">{secretCount}</span>
                      <span className="env-stat-label">Active Secrets</span>
                    </div>
                  </div>
                  <div className="env-stat">
                    <Clock size={14} />
                    <div>
                      <span className="env-stat-secondary">{lastUpdatedLabel}</span>
                      <span className="env-stat-label">Last Updated</span>
                    </div>
                  </div>
                  <div className="env-stat">
                    <Activity size={14} />
                    <div>
                      <span className="env-stat-secondary">{lastActivityLabel}</span>
                      <span className="env-stat-label">Last Activity</span>
                    </div>
                  </div>
                </div>

                <div className="env-card-footer">
                  <Clock size={12} />
                  <span>Created {formatDate(env.created_at)}</span>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* Create Modal */}
      <Modal
        isOpen={showCreateModal}
        onClose={closeCreateModal}
        title="Create Environment"
        footer={
          <>
            <button className="btn btn-secondary" onClick={closeCreateModal} disabled={isCreating}>
              Cancel
            </button>
            <button className="btn btn-primary" onClick={handleCreate} disabled={isCreating}>
              <Plus size={14} />
              {isCreating ? 'Creating...' : 'Create Environment'}
            </button>
          </>
        }
      >
        <div className="form-group" style={{ marginBottom: 0 }}>
          <label htmlFor="environment-name-input">Environment Name</label>
          <input
            id="environment-name-input"
            className="input mono"
            placeholder="e.g. staging"
            value={createName}
            onChange={(e) => setCreateName(e.target.value)}
            disabled={isCreating}
          />
        </div>
        {createError && <p className="env-form-error" role="alert">{createError}</p>}
      </Modal>

      {/* Rename Modal */}
      <Modal
        isOpen={Boolean(envPendingRename)}
        onClose={closeRenameModal}
        title="Rename Environment"
        initialFocusRef={renameInputRef}
        footer={
          <>
            <button className="btn btn-secondary" onClick={closeRenameModal} disabled={isRenaming}>
              Cancel
            </button>
            <button className="btn btn-primary" onClick={handleRename} disabled={isRenaming}>
              {isRenaming ? 'Saving...' : 'Save'}
            </button>
          </>
        }
      >
        <div className="form-group" style={{ marginBottom: 0 }}>
          <label htmlFor="rename-env-input">New Name</label>
          <input
            id="rename-env-input"
            ref={renameInputRef}
            className="input mono"
            value={renameName}
            onChange={(e) => setRenameName(e.target.value)}
            disabled={isRenaming}
            onKeyDown={(e) => { if (e.key === 'Enter') void handleRename(); }}
          />
        </div>
        {renameError && <p className="env-form-error" role="alert">{renameError}</p>}
      </Modal>

      {/* Delete Confirm */}
      <ConfirmDialog
        isOpen={Boolean(envPendingDelete)}
        title="Delete Environment"
        description={
          envPendingDelete
            ? `Delete "${envPendingDelete.name}"? All secrets and runtime tokens in this environment will be permanently deleted.`
            : ''
        }
        confirmLabel="Delete Environment"
        onConfirm={() => { void handleDelete(); }}
        onClose={() => { if (!isDeleting) setEnvPendingDelete(null); }}
        isBusy={isDeleting}
        tone="danger"
      />
    </div>
  );
}
