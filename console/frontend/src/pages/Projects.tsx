import { useCallback, useEffect, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { Bell, Plus, GitBranch, Users, Clock, TerminalSquare } from 'lucide-react';
import Modal from '../components/Modal';
import DashboardLoader from '../components/DashboardLoader';
import { useAuth } from '../auth/useAuth';
import {
  acceptInvitation,
  createProject,
  getInvitationByToken,
  listMyInvitations,
  listProjects,
  rejectInvitation,
} from '../lib/api';
import { formatRelativeTime } from '../lib/format';
import { getUserDisplayName } from '../lib/user';
import type { Project, InvitationSummary, InvitationDetail } from '../types/api';
import { ApiError } from '../lib/api';

export default function ProjectsPage() {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const { currentUser, authUser, accessToken, apiConfigError } = useAuth();
  const user = currentUser ?? authUser;
  const [projects, setProjects] = useState<Project[]>([]);
  const [invitations, setInvitations] = useState<InvitationSummary[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [notifOpen, setNotifOpen] = useState(false);
  const [inviteModal, setInviteModal] = useState<InvitationDetail | InvitationSummary | null>(null);
  const [inviteActionError, setInviteActionError] = useState<string | null>(null);
  const [inviteActionBusy, setInviteActionBusy] = useState(false);

  const refreshInvitations = useCallback(async () => {
    if (!accessToken || apiConfigError) {
      return;
    }
    try {
      const list = await listMyInvitations(accessToken);
      setInvitations(list);
    } catch {
      /* best-effort */
    }
  }, [accessToken, apiConfigError]);

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

    async function load() {
      setIsLoading(true);
      setError(null);

      try {
        const [projectList, invList] = await Promise.all([
          listProjects(accessToken!, { signal: controller.signal }),
          listMyInvitations(accessToken!, { signal: controller.signal }),
        ]);

        if (!isActive) {
          return;
        }

        setProjects(projectList);
        setInvitations(invList);
      } catch (loadError) {
        if (!isActive || controller.signal.aborted) {
          return;
        }

        setError((loadError as Error).message || 'Failed to load dashboard.');
      } finally {
        if (isActive) {
          setIsLoading(false);
        }
      }
    }

    void load();

    return () => {
      isActive = false;
      controller.abort();
    };
  }, [accessToken, apiConfigError]);

  const inviteTokenFromUrl = searchParams.get('invite');

  useEffect(() => {
    const rawInvite = inviteTokenFromUrl;
    const bearer = accessToken;
    if (!bearer || apiConfigError || !rawInvite) {
      return undefined;
    }

    let cancelled = false;

    async function openFromEmail() {
      try {
        const detail = await getInvitationByToken(rawInvite!, bearer!);
        if (!cancelled) {
          setInviteModal(detail);
          setSearchParams({}, { replace: true });
        }
      } catch (e) {
        if (!cancelled) {
          setError(
            e instanceof ApiError
              ? e.message
              : 'Could not open invitation from link. It may have expired.'
          );
          setSearchParams({}, { replace: true });
        }
      }
    }

    void openFromEmail();

    return () => {
      cancelled = true;
    };
  }, [accessToken, apiConfigError, inviteTokenFromUrl, setSearchParams]);

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

  const closeInviteModal = () => {
    if (inviteActionBusy) {
      return;
    }
    setInviteModal(null);
    setInviteActionError(null);
  };

  const handleAcceptInvite = async () => {
    if (!inviteModal || !accessToken) {
      return;
    }
    setInviteActionBusy(true);
    setInviteActionError(null);
    try {
      await acceptInvitation(inviteModal.id, accessToken);
      setInviteModal(null);
      setNotifOpen(false);
      await refreshInvitations();
      navigate(`/projects/${inviteModal.project_id}/overview`);
    } catch (e) {
      setInviteActionError(e instanceof ApiError ? e.message : 'Accept failed.');
    } finally {
      setInviteActionBusy(false);
    }
  };

  const handleRejectInvite = async () => {
    if (!inviteModal || !accessToken) {
      return;
    }
    setInviteActionBusy(true);
    setInviteActionError(null);
    try {
      await rejectInvitation(inviteModal.id, accessToken);
      setInviteModal(null);
      await refreshInvitations();
    } catch (e) {
      setInviteActionError(e instanceof ApiError ? e.message : 'Decline failed.');
    } finally {
      setInviteActionBusy(false);
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
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
          <div style={{ position: 'relative' }}>
            <button
              type="button"
              className="btn btn-secondary btn-icon"
              aria-label="Notifications"
              onClick={() => setNotifOpen((o) => !o)}
              id="projects-notifications-btn"
            >
              <Bell size={18} />
              {invitations.length > 0 ? (
                <span
                  className="badge badge-accent"
                  style={{
                    position: 'absolute',
                    top: -4,
                    right: -4,
                    minWidth: 18,
                    height: 18,
                    fontSize: 11,
                    lineHeight: '18px',
                    padding: '0 4px',
                    borderRadius: 999,
                  }}
                >
                  {invitations.length}
                </span>
              ) : null}
            </button>
            {notifOpen && (
              <div
                className="card"
                style={{
                  position: 'absolute',
                  right: 0,
                  top: 'calc(100% + 8px)',
                  zIndex: 50,
                  minWidth: 300,
                  maxHeight: 360,
                  overflow: 'auto',
                  boxShadow: '0 10px 40px rgba(0,0,0,0.15)',
                }}
              >
                <div style={{ padding: '12px 14px', borderBottom: '1px solid var(--border)' }}>
                  <strong>Invitations</strong>
                </div>
                {invitations.length === 0 ? (
                  <p style={{ padding: 16, margin: 0, color: 'var(--muted)' }}>No pending invites.</p>
                ) : (
                  <ul style={{ listStyle: 'none', margin: 0, padding: 0 }}>
                    {invitations.map((inv) => (
                      <li key={inv.id} style={{ borderBottom: '1px solid var(--border)' }}>
                        <button
                          type="button"
                          className="btn btn-ghost"
                          style={{
                            width: '100%',
                            textAlign: 'left',
                            justifyContent: 'flex-start',
                            padding: '12px 14px',
                            height: 'auto',
                            whiteSpace: 'normal',
                          }}
                          onClick={() => {
                            setInviteModal(inv);
                            setNotifOpen(false);
                          }}
                        >
                          <div>
                            <strong>{inv.project_name}</strong>
                            <div className="text-secondary" style={{ fontSize: 13 }}>
                              From {inv.inviter_email ?? 'project owner'} · expires{' '}
                              {formatRelativeTime(inv.expires_at)}
                            </div>
                          </div>
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            )}
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
        isOpen={Boolean(inviteModal)}
        onClose={closeInviteModal}
        title="Project invitation"
        footer={
          inviteModal ? (
            <>
              <button className="btn btn-secondary" onClick={closeInviteModal} disabled={inviteActionBusy}>
                Cancel
              </button>
              <button
                className="btn btn-secondary"
                onClick={handleRejectInvite}
                disabled={inviteActionBusy}
                id="invite-decline-btn"
              >
                Decline
              </button>
              <button
                className="btn btn-primary"
                onClick={handleAcceptInvite}
                disabled={inviteActionBusy}
                id="invite-accept-btn"
              >
                {inviteActionBusy ? 'Working…' : 'Accept'}
              </button>
            </>
          ) : null
        }
      >
        {inviteModal ? (
          <div className="invite-detail-modal">
            <p>
              <strong>{inviteModal.project_name ?? 'Project'}</strong>
            </p>
            <p className="text-secondary">
              Invited by <strong>{inviteModal.inviter_email ?? 'owner'}</strong> as{' '}
              {inviteModal.role}.
            </p>
            <p className="text-secondary">
              Secrets access: {inviteModal.can_push_pull_secrets ? 'enabled' : 'disabled'}
            </p>
            <p className="text-secondary" style={{ fontSize: 13 }}>
              Invitee: {inviteModal.email}
            </p>
            {inviteActionError ? (
              <p className="team-error" role="alert">
                {inviteActionError}
              </p>
            ) : null}
          </div>
        ) : null}
      </Modal>

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
