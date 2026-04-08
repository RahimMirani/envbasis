import { useEffect, useRef, useState } from 'react';
import { Link, NavLink, useNavigate } from 'react-router-dom';
import {
  ArrowLeft,
  Check,
  ChevronDown,
  LayoutDashboard,
  KeyRound,
  GitBranch,
  Users,
  Ticket,
  Settings,
  ScrollText,
  LogOut,
  Webhook,
} from 'lucide-react';
import { useAuth } from '../auth/useAuth';
import { getUserDisplayName, getUserInitials } from '../lib/user';
import type { Project } from '../types/api';

interface SidebarProps {
  basePath: string;
  currentProjectId: string;
  projectName: string;
  projectRole: 'owner' | 'member';
  projects: Project[];
}

function getProjectInitials(name: string): string {
  const parts = name.trim().split(/[\s._-]+/).filter(Boolean);

  if (parts.length >= 2) {
    return (parts[0][0] + parts[1][0]).toUpperCase();
  }

  return name.trim().slice(0, 2).toUpperCase() || 'PR';
}

export default function Sidebar({
  basePath,
  currentProjectId,
  projectName,
  projectRole,
  projects,
}: SidebarProps) {
  const navigate = useNavigate();
  const { currentUser, authUser, signOut } = useAuth();
  const user = currentUser ?? authUser;
  const [isProjectMenuOpen, setIsProjectMenuOpen] = useState(false);
  const projectMenuRef = useRef<HTMLDivElement | null>(null);

  const links = [
    { to: `${basePath}/overview`, icon: LayoutDashboard, label: 'Overview' },
    { to: `${basePath}/secrets`, icon: KeyRound, label: 'Secrets' },
    { to: `${basePath}/environments`, icon: GitBranch, label: 'Environments' },
    { to: `${basePath}/team`, icon: Users, label: 'Team' },
    { to: `${basePath}/tokens`, icon: Ticket, label: 'Runtime Tokens' },
    { to: `${basePath}/audit`, icon: ScrollText, label: 'Audit Logs' },
    { to: `${basePath}/webhooks`, icon: Webhook, label: 'Webhooks' },
    { to: `${basePath}/settings`, icon: Settings, label: 'Settings' },
  ];

  const currentProject = projects.find((project) => project.id === currentProjectId) ?? null;

  const formatProjectMeta = (project: Project) => {
    const countLabel = `${project.environment_count || 0} envs`;
    const roleLabel = project.role === 'owner' ? 'Owner access' : 'Member access';
    return `${countLabel} · ${roleLabel}`;
  };

  const handleSignOut = async () => {
    await signOut();
    navigate('/login');
  };

  useEffect(() => {
    if (!isProjectMenuOpen) {
      return undefined;
    }

    const handlePointerDown = (event: MouseEvent) => {
      if (!projectMenuRef.current?.contains(event.target as Node)) {
        setIsProjectMenuOpen(false);
      }
    };

    const handleEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setIsProjectMenuOpen(false);
      }
    };

    document.addEventListener('mousedown', handlePointerDown);
    document.addEventListener('keydown', handleEscape);

    return () => {
      document.removeEventListener('mousedown', handlePointerDown);
      document.removeEventListener('keydown', handleEscape);
    };
  }, [isProjectMenuOpen]);

  const handleProjectSelect = (project: Project) => {
    setIsProjectMenuOpen(false);
    navigate(`/projects/${project.id}/overview`);
  };

  return (
    <aside className="sidebar">
      <div className="sidebar-header">
        <Link to="/" className="sidebar-back-btn">
          <ArrowLeft size={14} />
          <span>All Projects</span>
        </Link>
      </div>

      <div className="sidebar-project-container" ref={projectMenuRef}>
        <button
          type="button"
          className={`sidebar-project-switcher ${isProjectMenuOpen ? 'is-open' : ''}`}
          onClick={() => setIsProjectMenuOpen((current) => !current)}
          aria-haspopup="menu"
          aria-expanded={isProjectMenuOpen}
        >
          <div className="sidebar-project-avatar">{getProjectInitials(projectName)}</div>
          <div className="sidebar-project-info">
            <span className="sidebar-project-name">{projectName}</span>
            <span className="sidebar-project-meta">
              {currentProject ? formatProjectMeta(currentProject) : projectRole === 'owner' ? 'Owner access' : 'Member access'}
            </span>
          </div>
          <ChevronDown size={14} className="sidebar-project-chevron" />
        </button>

        {isProjectMenuOpen ? (
          <div className="project-switcher-dropdown" role="menu">
            <div className="project-switcher-header">Switch project</div>
            <div className="project-switcher-list">
              {projects.map((project) => (
                <button
                  key={project.id}
                  type="button"
                  className={`project-switcher-item ${
                    project.id === currentProjectId ? 'active' : ''
                  }`}
                  onClick={() => handleProjectSelect(project)}
                  role="menuitem"
                >
                  <div className="project-switcher-item-avatar">
                    {getProjectInitials(project.name)}
                  </div>
                  <div className="project-switcher-item-info">
                    <span className="project-switcher-item-name">{project.name}</span>
                    <span className="project-switcher-item-env">{formatProjectMeta(project)}</span>
                  </div>
                  {project.id === currentProjectId ? (
                    <Check size={14} className="project-switcher-item-check" />
                  ) : null}
                </button>
              ))}
            </div>
            <div className="project-switcher-footer">
              <Link to="/" onClick={() => setIsProjectMenuOpen(false)}>
                View all projects
              </Link>
            </div>
          </div>
        ) : null}
      </div>

      <nav className="sidebar-nav">
        {links.map((link) => (
          <NavLink
            key={link.to}
            to={link.to}
            className={({ isActive }) => `sidebar-link ${isActive ? 'sidebar-link-active' : ''}`}
          >
            <link.icon size={16} className="sidebar-link-icon" />
            <span>{link.label}</span>
          </NavLink>
        ))}
      </nav>

      <div className="sidebar-bottom">
        <div className="sidebar-user">
          <div className="sidebar-user-avatar">{getUserInitials(user)}</div>
          <div className="sidebar-user-info">
            <span className="sidebar-user-name">{getUserDisplayName(user)}</span>
            <span className="sidebar-user-email">{user?.email || 'No email available'}</span>
          </div>
        </div>
        <button className="sidebar-logout-btn" onClick={handleSignOut}>
          <LogOut size={14} />
          <span>Sign Out</span>
        </button>
      </div>
    </aside>
  );
}
