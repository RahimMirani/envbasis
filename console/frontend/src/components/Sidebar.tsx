import {
  KeyboardEvent as ReactKeyboardEvent,
  MouseEvent as ReactMouseEvent,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import { Link, NavLink, useLocation, useNavigate } from 'react-router-dom';
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
  Search,
  Star,
} from 'lucide-react';
import { useAuth } from '../auth/useAuth';
import OwnerOnlyHint from './OwnerOnlyHint';
import { getUserDisplayName, getUserInitials } from '../lib/user';
import {
  getProjectDiscoveryState,
  isProjectPinned,
  isProjectRecent,
  markProjectVisited,
  matchesProjectSearch,
  sortProjectsForDiscovery,
  togglePinnedProject,
} from '../lib/projectDiscovery';
import type { Project } from '../types/api';

interface SidebarProps {
  basePath: string;
  currentProjectId: string;
  projectName: string;
  projectRole: 'owner' | 'member';
  projects: Project[];
  open?: boolean;
  onClose?: () => void;
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
  open = false,
  onClose,
}: SidebarProps) {
  const navigate = useNavigate();
  const location = useLocation();
  const { currentUser, authUser, signOut } = useAuth();
  const user = currentUser ?? authUser;
  const [isProjectMenuOpen, setIsProjectMenuOpen] = useState(false);
  const [projectSearch, setProjectSearch] = useState('');
  const [discoveryState, setDiscoveryState] = useState(() => getProjectDiscoveryState());
  const projectMenuRef = useRef<HTMLDivElement | null>(null);

  const links = [
    { to: `${basePath}/overview`, icon: LayoutDashboard, label: 'Overview' },
    { to: `${basePath}/secrets`, icon: KeyRound, label: 'Secrets' },
    { to: `${basePath}/environments`, icon: GitBranch, label: 'Environments' },
    { to: `${basePath}/team`, icon: Users, label: 'Team' },
    { to: `${basePath}/tokens`, icon: Ticket, label: 'Runtime Tokens' },
    { to: `${basePath}/audit`, icon: ScrollText, label: 'Audit Logs', ownerOnly: true },
    { to: `${basePath}/webhooks`, icon: Webhook, label: 'Webhooks', ownerOnly: true },
    { to: `${basePath}/settings`, icon: Settings, label: 'Settings', ownerOnly: true },
  ];

  const currentProject = projects.find((project) => project.id === currentProjectId) ?? null;
  const visibleProjects = useMemo(
    () =>
      sortProjectsForDiscovery(
        projects.filter((project) => matchesProjectSearch(project, projectSearch)),
        discoveryState,
        'recent'
      ),
    [discoveryState, projectSearch, projects]
  );

  const formatProjectMeta = (project: Project) => {
    const countLabel = `${project.environment_count || 0} envs`;
    const roleLabel = project.role === 'owner' ? 'Owner access' : 'Member access';
    const recentLabel = isProjectRecent(project.id, discoveryState) ? 'Recent' : null;
    return [countLabel, roleLabel, recentLabel].filter(Boolean).join(' · ');
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
    setProjectSearch('');
    setDiscoveryState(markProjectVisited(project.id));
    navigate(`/projects/${project.id}/overview`);
  };

  const handleTogglePinnedProject = (event: ReactMouseEvent, projectId: string) => {
    event.stopPropagation();
    event.preventDefault();
    setDiscoveryState(togglePinnedProject(projectId));
  };

  const handleSwitcherKeyDown = (event: ReactKeyboardEvent<HTMLDivElement>, project: Project) => {
    if (event.key !== 'Enter' && event.key !== ' ') {
      return;
    }

    event.preventDefault();
    handleProjectSelect(project);
  };

  const handleNavClick = () => {
    if (onClose) onClose();
  };

  return (
    <aside className={`sidebar${open ? ' sidebar-open' : ''}`}>
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
            <div className="project-switcher-search">
              <Search size={13} className="project-switcher-search-icon" />
              <input
                type="text"
                className="input project-switcher-search-input"
                placeholder="Search projects..."
                value={projectSearch}
                onChange={(event) => setProjectSearch(event.target.value)}
                aria-label="Search projects"
              />
            </div>
            <div className="project-switcher-list">
              {visibleProjects.length === 0 ? (
                <div className="project-switcher-empty">No matching projects.</div>
              ) : (
                visibleProjects.map((project) => {
                  const pinned = isProjectPinned(project.id, discoveryState);

                  return (
                    <div
                      key={project.id}
                      className={`project-switcher-item ${
                        project.id === currentProjectId ? 'active' : ''
                      }`}
                      onClick={() => handleProjectSelect(project)}
                      role="menuitem"
                      tabIndex={0}
                      onKeyDown={(event) => handleSwitcherKeyDown(event, project)}
                    >
                      <div className="project-switcher-item-avatar">
                        {getProjectInitials(project.name)}
                      </div>
                      <div className="project-switcher-item-info">
                        <span className="project-switcher-item-name">{project.name}</span>
                        <span className="project-switcher-item-env">{formatProjectMeta(project)}</span>
                      </div>
                      <button
                        type="button"
                        className={`project-switcher-pin ${pinned ? 'active' : ''}`}
                        aria-label={pinned ? `Unpin ${project.name}` : `Pin ${project.name}`}
                        onClick={(event) => handleTogglePinnedProject(event, project.id)}
                      >
                        <Star size={13} fill={pinned ? 'currentColor' : 'none'} />
                      </button>
                      {project.id === currentProjectId ? (
                        <Check size={14} className="project-switcher-item-check" />
                      ) : null}
                    </div>
                  );
                })
              )}
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
        {links.map((link) => {
          const isLocked = Boolean(link.ownerOnly) && projectRole !== 'owner';

          if (isLocked) {
            return (
              <OwnerOnlyHint
                key={link.to}
                message={`${link.label} is available to project owners only.`}
                className="sidebar-owner-only-hint"
              >
                <button
                  type="button"
                  className={`sidebar-link sidebar-link-locked ${
                    location.pathname === link.to ? 'sidebar-link-active' : ''
                  }`}
                  aria-disabled="true"
                  tabIndex={-1}
                >
                  <span className="sidebar-link-content">
                    <link.icon size={16} className="sidebar-link-icon" />
                    <span>{link.label}</span>
                  </span>
                  <span className="owner-only-chip owner-only-chip-sidebar">Owner only</span>
                </button>
              </OwnerOnlyHint>
            );
          }

          return (
            <NavLink
              key={link.to}
              to={link.to}
              className={({ isActive }) => `sidebar-link ${isActive ? 'sidebar-link-active' : ''}`}
              onClick={handleNavClick}
            >
              <span className="sidebar-link-content">
                <link.icon size={16} className="sidebar-link-icon" />
                <span>{link.label}</span>
              </span>
            </NavLink>
          );
        })}
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
