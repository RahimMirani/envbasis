import { useEffect, useRef, useState } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { Check, ChevronDown, GitBranch, Layers, LogOut, Menu } from 'lucide-react';
import { useAuth } from '../auth/useAuth';
import { getUserDisplayName, getUserInitials } from '../lib/user';
import type { Environment } from '../types/api';

interface TopBarProps {
  projectName?: string;
  environments?: Environment[];
  currentEnv?: string;
  onEnvChange?: (env: string) => void;
  onMenuOpen?: () => void;
  fullWidth?: boolean;
}

function envDotClass(environmentName: string): string {
  return `env-dot env-dot-${environmentName.toLowerCase()}`;
}

export default function TopBar({
  projectName,
  environments = [],
  currentEnv = 'all',
  onEnvChange,
  onMenuOpen,
  fullWidth = false,
}: TopBarProps) {
  const pageTitles: Record<string, string> = {
    overview: 'Overview',
    secrets: 'Secrets',
    'provider-keys': 'Proxy secrets',
    environments: 'Environments',
    team: 'Team',
    'machine-identities': 'Machine Identities',
    tokens: 'Machine Identities',
    audit: 'Audit Logs',
    settings: 'Settings',
    governance: 'Access & Approvals',
  };
  const location = useLocation();
  const navigate = useNavigate();
  const { currentUser, authUser, signOut } = useAuth();
  const user = currentUser ?? authUser;
  const pathSegments = location.pathname.split('/').filter(Boolean);
  const activeSegment = pathSegments[pathSegments.length - 1] ?? '';
  const pageTitle = pageTitles[activeSegment] ?? null;
  const projectBasePath =
    pathSegments[0] === 'projects' && pathSegments[1] ? `/projects/${pathSegments[1]}` : null;
  const [isEnvMenuOpen, setIsEnvMenuOpen] = useState(false);
  const envMenuRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!isEnvMenuOpen) {
      return undefined;
    }

    const handlePointerDown = (event: MouseEvent) => {
      if (!envMenuRef.current?.contains(event.target as Node)) {
        setIsEnvMenuOpen(false);
      }
    };

    const handleEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setIsEnvMenuOpen(false);
      }
    };

    document.addEventListener('mousedown', handlePointerDown);
    document.addEventListener('keydown', handleEscape);

    return () => {
      document.removeEventListener('mousedown', handlePointerDown);
      document.removeEventListener('keydown', handleEscape);
    };
  }, [isEnvMenuOpen]);

  const handleEnvSelect = (env: string) => {
    setIsEnvMenuOpen(false);
    onEnvChange?.(env);
  };

  const handleSignOut = async () => {
    await signOut();
    navigate('/login');
  };

  return (
    <header className={`topbar${fullWidth ? ' topbar-full' : ''}`}>
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
        {onEnvChange && (
          <div className="topbar-env" ref={envMenuRef}>
            <button
              type="button"
              id="env-selector"
              className={`topbar-env-trigger ${isEnvMenuOpen ? 'is-open' : ''}`}
              onClick={() => setIsEnvMenuOpen((current) => !current)}
              aria-haspopup="listbox"
              aria-expanded={isEnvMenuOpen}
              aria-label="Select environment"
            >
              {currentEnv === 'all' ? (
                <Layers size={14} className="topbar-env-icon" />
              ) : (
                <span className={envDotClass(currentEnv)} />
              )}
              <span className="topbar-env-name">
                {currentEnv === 'all' ? 'All environments' : currentEnv}
              </span>
              <ChevronDown size={13} className="topbar-env-chevron" />
            </button>
            {isEnvMenuOpen && (
              <div className="topbar-env-menu" role="listbox" aria-label="Environments">
                <button
                  type="button"
                  role="option"
                  aria-selected={currentEnv === 'all'}
                  className={`topbar-env-option ${currentEnv === 'all' ? 'is-active' : ''}`}
                  onClick={() => handleEnvSelect('all')}
                >
                  <Layers size={14} className="topbar-env-icon" />
                  <span>All environments</span>
                  {currentEnv === 'all' && <Check size={14} className="topbar-env-check" />}
                </button>
                <div className="topbar-env-menu-divider" />
                {environments.length === 0 ? (
                  <p className="topbar-env-empty">No environments yet.</p>
                ) : (
                  environments.map((env) => (
                    <button
                      key={env.id}
                      type="button"
                      role="option"
                      aria-selected={currentEnv === env.name}
                      className={`topbar-env-option ${currentEnv === env.name ? 'is-active' : ''}`}
                      onClick={() => handleEnvSelect(env.name)}
                    >
                      <span className={envDotClass(env.name)} />
                      <span>{env.name}</span>
                      {currentEnv === env.name && <Check size={14} className="topbar-env-check" />}
                    </button>
                  ))
                )}
                {projectBasePath && (
                  <>
                    <div className="topbar-env-menu-divider" />
                    <Link
                      to={`${projectBasePath}/environments`}
                      className="topbar-env-option topbar-env-manage"
                      onClick={() => setIsEnvMenuOpen(false)}
                    >
                      <GitBranch size={14} className="topbar-env-icon" />
                      <span>Manage environments</span>
                    </Link>
                  </>
                )}
              </div>
            )}
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
