import { useEffect, useState } from 'react';
import { AlertTriangle } from 'lucide-react';
import { useNavigate, useOutletContext } from 'react-router-dom';
import { useAuth } from '../auth/useAuth';
import ConfirmDialog from '../components/ConfirmDialog';
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
  const [name, setName] = useState(project.name);
  const [description, setDescription] = useState(project.description || '');
  const [error, setError] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);
  const [isSaving, setIsSaving] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);

  useEffect(() => {
    setName(project.name);
    setDescription(project.description || '');
  }, [project.description, project.name]);

  const handleSave = async () => {
    const trimmedName = name.trim();
    const trimmedDescription = description.trim();
    const nextDescription = trimmedDescription || null;
    const updates: { name?: string; description?: string | null } = {};

    if (!trimmedName) {
      setError('Project name is required.');
      setSuccessMessage(null);
      return;
    }

    if (trimmedName !== project.name) {
      updates.name = trimmedName;
    }

    if (nextDescription !== (project.description || null)) {
      updates.description = nextDescription;
    }

    if (Object.keys(updates).length === 0) {
      setSuccessMessage('No changes to save.');
      setError(null);
      return;
    }

    setIsSaving(true);
    setError(null);
    setSuccessMessage(null);

    try {
      const updatedProject = await updateProject(project.id, accessToken!, updates);
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
          {!canManageProject && (
            <p className="settings-note">Only project owners can update these settings.</p>
          )}
          <div className="form-group">
            <label htmlFor="project-name-input">Project Name</label>
            <input
              id="project-name-input"
              className="input mono"
              value={name}
              onChange={(event) => setName(event.target.value)}
              disabled={!canManageProject || isSaving || isDeleting}
            />
          </div>
          <div className="form-group" style={{ marginBottom: 0 }}>
            <label htmlFor="project-desc-input">Description</label>
            <input
              id="project-desc-input"
              className="input"
              value={description}
              onChange={(event) => setDescription(event.target.value)}
              disabled={!canManageProject || isSaving || isDeleting}
            />
          </div>
          {error && (
            <p className="settings-error" role="alert">
              {error}
            </p>
          )}
          {successMessage && <p className="settings-success">{successMessage}</p>}
          <div className="settings-card-footer">
            <button
              className="btn btn-primary btn-sm"
              id="save-settings-btn"
              onClick={handleSave}
              disabled={!canManageProject || isSaving || isDeleting}
            >
              {isSaving ? 'Saving...' : 'Save Changes'}
            </button>
          </div>
        </div>
      </div>

      <div className="settings-section">
        <h3 className="settings-section-title settings-danger-title">
          <AlertTriangle size={16} />
          Danger Zone
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
            <button
              className="btn btn-danger btn-sm"
              id="delete-project-btn"
              onClick={() => setShowDeleteConfirm(true)}
              disabled={!canManageProject || isSaving || isDeleting}
            >
              {isDeleting ? 'Deleting...' : 'Delete Project'}
            </button>
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
