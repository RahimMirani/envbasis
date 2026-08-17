import { NavLink, useNavigate } from 'react-router-dom';
import { LayoutGrid, ScrollText, UserCog, LogOut } from 'lucide-react';
import { useAuth } from '../auth/useAuth';
import { getUserDisplayName, getUserInitials } from '../lib/user';

interface GlobalSidebarProps {
  open?: boolean;
  onClose?: () => void;
}

export default function GlobalSidebar({ open = false, onClose }: GlobalSidebarProps) {
  const navigate = useNavigate();
  const { currentUser, authUser, signOut } = useAuth();
  const user = currentUser ?? authUser;

  const handleSignOut = async () => {
    await signOut();
    navigate('/login');
  };

  const handleNavClick = () => {
    if (onClose) onClose();
  };

  return (
    <>
      <aside className={`global-sidebar${open ? ' sidebar-open' : ''}`}>
        <div className="global-sidebar-brand">
          <span className="global-sidebar-logo">envbasis</span>
          <span className="global-sidebar-logo-dot" />
        </div>

        <nav className="global-sidebar-nav">
          <div className="global-sidebar-section-label">Workspace</div>
          <NavLink
            to="/"
            end
            className={({ isActive }) => `sidebar-link ${isActive ? 'sidebar-link-active' : ''}`}
            onClick={handleNavClick}
          >
            <LayoutGrid size={16} className="sidebar-link-icon" />
            <span>Projects</span>
          </NavLink>

          <div className="global-sidebar-section-label" style={{ marginTop: 'var(--space-4)' }}>Tools</div>
          <NavLink
            to="/audit"
            className={({ isActive }) => `sidebar-link ${isActive ? 'sidebar-link-active' : ''}`}
            onClick={handleNavClick}
          >
            <ScrollText size={16} className="sidebar-link-icon" />
            <span>Audit Logs</span>
          </NavLink>
        </nav>

        <div className="global-sidebar-bottom">
          <NavLink
            to="/account"
            className={({ isActive }) => `sidebar-link ${isActive ? 'sidebar-link-active' : ''}`}
            onClick={handleNavClick}
          >
            <UserCog size={16} className="sidebar-link-icon" />
            <span>Account Settings</span>
          </NavLink>

          <div className="global-sidebar-divider" />

          <div className="sidebar-user">
            <div className="sidebar-user-avatar">{getUserInitials(user)}</div>
            <div className="sidebar-user-info">
              <span className="sidebar-user-name">{getUserDisplayName(user)}</span>
              <span className="sidebar-user-email">{user?.email || ''}</span>
            </div>
          </div>
          <button className="sidebar-logout-btn" onClick={() => { void handleSignOut(); }}>
            <LogOut size={14} />
            <span>Sign Out</span>
          </button>
        </div>
      </aside>
    </>
  );
}
