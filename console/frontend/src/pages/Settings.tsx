import { useEffect, useState } from 'react';
import { AlertTriangle } from 'lucide-react';
import { Navigate, useNavigate, useOutletContext } from 'react-router-dom';
import { useAuth } from '../auth/useAuth';
import ConfirmDialog from '../components/ConfirmDialog';
import OwnerOnlyHint from '../components/OwnerOnlyHint';
import { deleteProject, updateProject } from '../lib/api';
import type { Project } from '../types/api';

interface OutletContextType {
  currentProject: Project;
  onProjectUpdated: (project: Project) => void;
  canManageProject: boolean;
}

export default function SettingsPage() {
  const navigate = useNavigate();
  const { currentProject, onProjectUpdated, canManageProject } =
    useOutletContext<OutletContextType>();
  const { accessToken } = useAuth();
  const project = currentProject;

  if (!canManageProject) {
    return <Navigate to={`/projects/${project.id}/overview`} replace />;
  }

  const [name, setName] = useState(project.name);
  const [description, setDescription] = useState(project.description ?? '');
  const [auditLogVisibility, setAuditLogVisibility] = useState(project.audit_log_visibility);
  const [error, setError] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);
  const [isSaving, setIsSaving] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);

  useEffect(() => {
    setName(project.name);
    setDescription(project.description ?? '');
    setAuditLogVisibility(project.audit_log_visibility);
  }, [project.name, project.description, project.audit_log_visibility]);

  const handleSave = async () => {
    const trimmedName = name.trim();
    if (!trimmedName) {
      setError('Project name is required.');
      return;
    }
    const trimmedDesc = description.trim() || null;
    const noChanges =
      trimmedName === project.name &&
      trimmedDesc === (project.description ?? null) &&
      auditLogVisibility === project.audit_log_visibility;
    if (noChanges) {
      setSuccessMessage('No changes to save.');
      setError(null);
      return;
    }

    setIsSaving(true);
    setError(null);
    setSuccessMessage(null);

    try {
      const updatedProject = await updateProject(project.id, accessToken!, {
        name: trimmedName,
        description: trimmedDesc,
        audit_log_visibility: auditLogVisibility,
      });
      onProjectUpdated(updatedProject);
      setSuccessMessage('Project settings updated.');
    } catch (saveError) {
      setError((saveError as Error).message || 'Failed to update project.');
    } finally {
      setIsSaving(false);
    }
  };

  const handleDelete = async () => {
    setIsDeleting(true);
    setError(null);
    setSuccessMessage(null);

    try {
      await deleteProject(project.id, accessToken!);
      navigate('/', { replace: true });
    } catch (deleteError) {
      setError((deleteError as Error).message || 'Failed to delete project.');
      setIsDeleting(false);
    }
  };

  return (
    <div className="settings-page animate-in">
      <div className="page-header">
        <div>
          <h1 className="page-heading">Settings</h1>
          <p className="page-subtitle">Configure your project settings.</p>
        </div>
      </div>

      <div className="settings-section">
        <h3 className="settings-section-title">General</h3>
        <div className="card settings-card">
          <div className="form-group">
            <label htmlFor="settings-name-input">Project name</label>
            <input
              id="settings-name-input"
              className="input"
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              disabled={!canManageProject || isSaving || isDeleting}
              placeholder="My project"
            />
          </div>
          <div className="form-group" style={{ marginBottom: 0 }}>
            <label htmlFor="settings-desc-input">Description</label>
            <textarea
              id="settings-desc-input"
              className="input"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              disabled={!canManageProject || isSaving || isDeleting}
              placeholder="Optional description"
              rows={2}
            />
          </div>
        </div>
      </div>

      <div className="settings-section">
        <h3 className="settings-section-title">Audit Logs</h3>
        <div className="card settings-card">
          <p className="settings-note">
            Choose who can view audit logs for this project.
            {auditLogVisibility === 'specific' && (
              <> Grant access to individual members from the <strong>Team</strong> page.</>
            )}
          </p>
          <div className="form-group" style={{ marginBottom: 0 }}>
            <label htmlFor="audit-log-visibility-select">Visibility</label>
            <select
              id="audit-log-visibility-select"
              className="input select"
              value={auditLogVisibility}
              onChange={(event) =>
                setAuditLogVisibility(event.target.value as 'owner_only' | 'members' | 'specific')
              }
              disabled={!canManageProject || isSaving || isDeleting}
            >
              <option value="owner_only">Owner only</option>
              <option value="members">All members</option>
              <option value="specific">Specific members</option>
            </select>
          </div>
        </div>
      </div>

      <div className="settings-section">
        <div className="card settings-card" style={{ borderColor: 'transparent', background: 'transparent', boxShadow: 'none', padding: 0 }}>
          {error && (
            <p className="settings-error" role="alert" style={{ marginBottom: 'var(--space-3)' }}>
              {error}
            </p>
          )}
          {successMessage && <p className="settings-success" style={{ marginBottom: 'var(--space-3)' }}>{successMessage}</p>}
          <div style={{ display: 'flex' }}>
            {canManageProject ? (
              <button
                className="btn btn-primary btn-sm"
                id="save-settings-btn"
                onClick={handleSave}
                disabled={isSaving || isDeleting}
              >
                {isSaving ? 'Saving...' : 'Save Changes'}
              </button>
            ) : (
              <OwnerOnlyHint message="Only project owners can save settings changes.">
                <button className="btn btn-primary btn-sm" id="save-settings-btn" disabled>
                  Save Changes
                </button>
              </OwnerOnlyHint>
            )}
          </div>
        </div>
      </div>

      <div className="settings-section">
        <h3 className="settings-section-title settings-danger-title">
          <AlertTriangle size={16} />
          Danger Zone
          {!canManageProject && <span className="owner-only-chip">Owner only</span>}
        </h3>
        <div className="card settings-card settings-danger-card">
          <div className="settings-danger-item">
            <div>
              <strong>Delete Project</strong>
              <p>
                Permanently delete this project and all its secrets, tokens, and data. This action
                cannot be undone.
              </p>
            </div>
            {canManageProject ? (
              <button
                className="btn btn-danger btn-sm"
                id="delete-project-btn"
                onClick={() => setShowDeleteConfirm(true)}
                disabled={isSaving || isDeleting}
              >
                {isDeleting ? 'Deleting...' : 'Delete Project'}
              </button>
            ) : (
              <OwnerOnlyHint message="Only project owners can delete this project.">
                <button className="btn btn-danger btn-sm" id="delete-project-btn" disabled>
                  Delete Project
                </button>
              </OwnerOnlyHint>
            )}
          </div>
        </div>
      </div>
      <ConfirmDialog
        isOpen={showDeleteConfirm}
        title="Delete Project"
        description={`Delete project "${project.name}"? This cannot be undone.`}
        confirmLabel="Delete Project"
        onConfirm={handleDelete}
        onClose={() => {
          if (!isDeleting) {
            setShowDeleteConfirm(false);
          }
        }}
        isBusy={isDeleting}
      />
    </div>
  );
}
