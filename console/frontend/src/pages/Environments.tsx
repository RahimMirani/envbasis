import { useState } from 'react';
import { Plus, Activity, Clock, KeyRound } from 'lucide-react';
import { useOutletContext } from 'react-router-dom';
import Modal from '../components/Modal';
import { useAuth } from '../auth/useAuth';
import { createEnvironment } from '../lib/api';
import { formatDate, formatRelativeTime, getEnvironmentColor } from '../lib/format';
import type { Project, Environment, SecretStats } from '../types/api';

interface OutletContextType {
  currentProject: Project;
  environments: Environment[];
  canManageProject: boolean;
  onEnvironmentCreated: (env: Environment) => void;
  secretStats: SecretStats | null;
  isSecretStatsLoading: boolean;
}

export default function EnvironmentsPage() {
  const {
    currentProject,
    environments,
    canManageProject,
    onEnvironmentCreated,
    secretStats,
    isSecretStatsLoading,
  } = useOutletContext<OutletContextType>();
  const { accessToken } = useAuth();
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [name, setName] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const secretStatsByEnvironmentId = new Map(
    (secretStats?.environments || []).map((item) => [item.environment_id, item])
  );

  const openCreateModal = () => {
    setShowCreateModal(true);
    setName('');
    setError(null);
  };

  const closeCreateModal = () => {
    if (isSubmitting) {
      return;
    }

    setShowCreateModal(false);
    setName('');
    setError(null);
  };

  const handleCreateEnvironment = async () => {
    const trimmedName = name.trim();

    if (!trimmedName) {
      setError('Environment name is required.');
      return;
    }

    setIsSubmitting(true);
    setError(null);

    try {
      const environment = await createEnvironment(currentProject.id, accessToken!, {
        name: trimmedName,
      });

      onEnvironmentCreated(environment);
      setShowCreateModal(false);
      setName('');
      setError(null);
    } catch (createError) {
      setError((createError as Error).message || 'Failed to create environment.');
    } finally {
      setIsSubmitting(false);
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
        <p className="env-note">Only owners can create environments for this project.</p>
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

      <Modal
        isOpen={showCreateModal}
        onClose={closeCreateModal}
        title="Create Environment"
        footer={
          <>
            <button
              className="btn btn-secondary"
              onClick={closeCreateModal}
              disabled={isSubmitting}
            >
              Cancel
            </button>
            <button
              className="btn btn-primary"
              onClick={handleCreateEnvironment}
              disabled={isSubmitting}
            >
              <Plus size={14} />
              {isSubmitting ? 'Creating...' : 'Create Environment'}
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
            value={name}
            onChange={(event) => setName(event.target.value)}
            disabled={isSubmitting}
          />
        </div>
        {error && (
          <p className="env-form-error" role="alert">
            {error}
          </p>
        )}
      </Modal>
    </div>
  );
}
