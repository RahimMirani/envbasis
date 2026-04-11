import { Link, useLocation, useNavigate } from 'react-router-dom';
import { LogOut, Menu } from 'lucide-react';
import { useAuth } from '../auth/useAuth';
import { getUserDisplayName, getUserInitials } from '../lib/user';
import type { Environment } from '../types/api';

interface TopBarProps {
  projectName?: string;
  environments?: Environment[];
  currentEnv?: string;
  onEnvChange?: (env: string) => void;
  onMenuOpen?: () => void;
}

export default function TopBar({
  projectName,
  environments = [],
  currentEnv = 'all',
  onEnvChange,
  onMenuOpen,
}: TopBarProps) {
  const pageTitles: Record<string, string> = {
    overview: 'Overview',
    secrets: 'Secrets',
    environments: 'Environments',
    team: 'Team',
    tokens: 'Runtime Tokens',
    audit: 'Audit Logs',
    settings: 'Settings',
  };
  const location = useLocation();
  const navigate = useNavigate();
  const { currentUser, authUser, signOut } = useAuth();
  const user = currentUser ?? authUser;
  const pathSegments = location.pathname.split('/').filter(Boolean);
  const activeSegment = pathSegments[pathSegments.length - 1] ?? '';
  const pageTitle = pageTitles[activeSegment] ?? null;

  const handleSignOut = async () => {
    await signOut();
    navigate('/login');
  };

  return (
    <header className="topbar">
      <div className="topbar-left">
        {onMenuOpen && (
          <button className="topbar-hamburger" onClick={onMenuOpen} aria-label="Open navigation">
            <Menu size={20} />
          </button>
        )}
        <Link to="/" className="topbar-logo">
          EnvBasis
        </Link>
        {projectName && (
          <>
            <span className="topbar-separator">/</span>
            <span className="topbar-project mono">{projectName}</span>
            {pageTitle ? (
              <>
                <span className="topbar-separator">/</span>
                <span className="topbar-page">{pageTitle}</span>
              </>
            ) : null}
          </>
        )}
      </div>

      <div className="topbar-right">
        {environments.length > 0 && onEnvChange && (
          <div className="topbar-env-select">
            <select
              value={currentEnv}
              onChange={(e) => onEnvChange(e.target.value)}
              className="input select"
              id="env-selector"
            >
              <option value="all">All Environments</option>
              {environments.map((env) => (
                <option key={env.id} value={env.name}>
                  {env.name}
                </option>
              ))}
            </select>
          </div>
        )}

        <div className="topbar-user">
          <div className="topbar-avatar">{getUserInitials(user)}</div>
          <span className="topbar-username">{getUserDisplayName(user)}</span>
          <button className="btn btn-ghost btn-icon btn-sm" onClick={handleSignOut} aria-label="Sign out">
            <LogOut size={16} />
          </button>
        </div>
      </div>
    </header>
  );
}
