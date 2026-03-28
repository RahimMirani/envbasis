import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Plus, GitBranch, Users, Clock, TerminalSquare } from 'lucide-react';
import Modal from '../components/Modal';
import DashboardLoader from '../components/DashboardLoader';
import { useAuth } from '../auth/useAuth';
import { createProject, listProjects } from '../lib/api';
import { formatRelativeTime } from '../lib/format';
import { getUserDisplayName } from '../lib/user';
import type { Project } from '../types/api';

export default function ProjectsPage() {
  const navigate = useNavigate();
  const { currentUser, authUser, accessToken, apiConfigError } = useAuth();
  const user = currentUser ?? authUser;
  const [projects, setProjects] = useState<Project[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);

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

    async function loadProjects() {
      setIsLoading(true);
      setError(null);

      try {
        const projectList = await listProjects(accessToken!, {
          signal: controller.signal,
        });

        if (!isActive) {
          return;
        }

        setProjects(projectList);
      } catch (loadError) {
        if (!isActive || controller.signal.aborted) {
          return;
        }

        setError((loadError as Error).message || 'Failed to load projects.');
      } finally {
        if (isActive) {
          setIsLoading(false);
        }
      }
    }

    void loadProjects();

    return () => {
      isActive = false;
      controller.abort();
    };
  }, [accessToken, apiConfigError]);

  const openCreateModal = () => {
    setShowCreateModal(true);
    setName('');
    setDescription('');
    setSubmitError(null);
  };

  const closeCreateModal = () => {
    if (isSubmitting) {
      return;
    }

    setShowCreateModal(false);
    setName('');
    setDescription('');
    setSubmitError(null);
  };

  const handleCreateProject = async () => {
    const trimmedName = name.trim();
    const trimmedDescription = description.trim();

    if (!trimmedName) {
      setSubmitError('Project name is required.');
      return;
    }

    setIsSubmitting(true);
    setSubmitError(null);

    try {
      const project = await createProject(accessToken!, {
        name: trimmedName,
        description: trimmedDescription || null,
      });

      setProjects((currentProjects) => [project, ...currentProjects]);
      setShowCreateModal(false);
      setName('');
      setDescription('');
      setSubmitError(null);
      navigate(`/projects/${project.id}/overview`);
    } catch (createError) {
      setSubmitError((createError as Error).message || 'Failed to create project.');
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="projects-page animate-in">
      <div className="projects-hero">
        <div className="projects-hero-content">
          <h1 className="projects-hero-heading">Welcome back, {getUserDisplayName(user)}</h1>
          <p className="projects-hero-subtitle">
            You have {projects.length} active projects managing secure environments.
          </p>
        </div>
        <button
          className="btn btn-primary btn-lg"
          id="create-project-btn"
          onClick={openCreateModal}
        >
          <Plus size={18} />
          <span>New Project</span>
        </button>
      </div>

      {error && (
        <div className="auth-status auth-status-error" role="alert">
          <span>{error}</span>
        </div>
      )}

      {isLoading ? (
        <DashboardLoader title="Loading dashboard" description="Fetching your project list." />
      ) : projects.length === 0 ? (
        <div className="empty-state">
          <h3>No projects yet</h3>
          <p>Create your first project to start managing environments and secrets.</p>
          <button className="btn btn-primary" onClick={openCreateModal}>
            <Plus size={14} />
            Create Project
          </button>
        </div>
      ) : (
        <div className="projects-grid stagger-in">
          {projects.map((project, i) => (
            <div
              key={project.id}
              className="project-card glow-effect"
              onClick={() => navigate(`/projects/${project.id}/overview`)}
              role="button"
              tabIndex={0}
              style={{ '--animation-order': i } as React.CSSProperties}
            >
              <div className="project-card-header">
                <div className="project-card-icon-wrapper">
                  <TerminalSquare size={20} className="project-card-icon-svg" />
                </div>
                <div className="project-card-status">
                  <span className="status-dot healthy"></span>
                  <span>Active</span>
                </div>
              </div>

              <div className="project-card-body">
                <h3 className="project-card-title">{project.name}</h3>
                <p className="project-card-desc">{project.description}</p>
              </div>

              <div className="project-card-footer">
                <div className="project-card-metrics">
                  <div className="metric">
                    <GitBranch size={13} />
                    <span>{project.environment_count || 0} Envs</span>
                  </div>
                  <div className="metric">
                    <Users size={13} />
                    <span>{project.member_count || 0} Team</span>
                  </div>
                </div>
                <div className="project-card-activity">
                  <Clock size={12} />
                  <span>{formatRelativeTime(project.last_activity_at || project.created_at)}</span>
                </div>
              </div>
            </div>
          ))}

          <div
            className="project-card card-create glow-effect"
            role="button"
            tabIndex={0}
            style={{ '--animation-order': projects.length } as React.CSSProperties}
            onClick={openCreateModal}
          >
            <div className="card-create-content">
              <div className="card-create-icon-wrapper">
                <Plus size={28} />
              </div>
              <h3>Create Project</h3>
              <p>Setup a new secure environment.</p>
            </div>
          </div>
        </div>
      )}

      <Modal
        isOpen={showCreateModal}
        onClose={closeCreateModal}
        title="Create Project"
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
              onClick={handleCreateProject}
              disabled={isSubmitting}
            >
              <Plus size={14} />
              {isSubmitting ? 'Creating...' : 'Create Project'}
            </button>
          </>
        }
      >
        <div className="form-group">
          <label htmlFor="project-name-input">Project Name</label>
          <input
            id="project-name-input"
            className="input mono"
            placeholder="e.g. envbasis-api"
            value={name}
            onChange={(event) => setName(event.target.value)}
            disabled={isSubmitting}
          />
        </div>
        <div className="form-group" style={{ marginBottom: 0 }}>
          <label htmlFor="project-description-input">Description</label>
          <input
            id="project-description-input"
            className="input"
            placeholder="What this project is for"
            value={description}
            onChange={(event) => setDescription(event.target.value)}
            disabled={isSubmitting}
          />
        </div>
        {submitError && (
          <p className="projects-form-error" role="alert">
            {submitError}
          </p>
        )}
      </Modal>
    </div>
  );
}
