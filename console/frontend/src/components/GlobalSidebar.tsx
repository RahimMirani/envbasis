import { useState } from 'react';
import { NavLink, useNavigate } from 'react-router-dom';
import { LayoutGrid, ScrollText, Trophy, UserCog, LogOut, X, Mail } from 'lucide-react';
import { useAuth } from '../auth/useAuth';
import { getUserDisplayName, getUserInitials } from '../lib/user';

function HackathonModal({ onClose }: { onClose: () => void }) {
  return (
    <div className="hackathon-overlay" onClick={onClose}>
      <div className="hackathon-modal" onClick={(e) => e.stopPropagation()}>
        <div className="hackathon-border-ray" />
        <div className="hackathon-content">
          <div className="hackathon-header">
            <div className="hackathon-eyebrow">
              <Trophy size={12} />
              <span>Hackathon</span>
            </div>
            <button className="hackathon-close" onClick={onClose} aria-label="Close">
              <X size={14} />
            </button>
          </div>

          <div className="hackathon-body">
            <h2 className="hackathon-title">Something big<br />is coming.</h2>
            <p className="hackathon-desc">
              We&apos;re building the Hackathon feature from the ground up.
              Expect it to ship soon.
            </p>
          </div>

          <div className="hackathon-footer">
            <p className="hackathon-footer-label">Have ideas? Reach out directly.</p>
            <a className="hackathon-email" href="mailto:abdulrahimmirani@baselinelabs.org">
              <Mail size={13} />
              abdulrahimmirani@baselinelabs.org
            </a>
          </div>
        </div>
      </div>
    </div>
  );
}

interface GlobalSidebarProps {
  open?: boolean;
  onClose?: () => void;
}

export default function GlobalSidebar({ open = false, onClose }: GlobalSidebarProps) {
  const navigate = useNavigate();
  const { currentUser, authUser, signOut } = useAuth();
  const user = currentUser ?? authUser;
  const [hackathonOpen, setHackathonOpen] = useState(false);

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

          <button
            type="button"
            className="sidebar-link sidebar-link-hackathon"
            onClick={() => setHackathonOpen(true)}
          >
            <Trophy size={16} className="sidebar-link-icon" />
            <span>Hackathon</span>
            <span className="coming-soon-badge">
              <span className="coming-soon-text">Coming soon</span>
            </span>
          </button>
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

      {hackathonOpen && <HackathonModal onClose={() => setHackathonOpen(false)} />}
    </>
  );
}
