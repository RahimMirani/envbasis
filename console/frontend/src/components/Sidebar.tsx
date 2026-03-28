import { NavLink } from 'react-router-dom';
import {
  LayoutDashboard,
  KeyRound,
  GitBranch,
  Users,
  Ticket,
  Settings,
  ScrollText,
} from 'lucide-react';
interface SidebarProps {
  basePath: string;
  isOwner?: boolean;
}

export default function Sidebar({ basePath, isOwner = false }: SidebarProps) {
  const links = [
    { to: `${basePath}/overview`, icon: LayoutDashboard, label: 'Overview' },
    { to: `${basePath}/secrets`, icon: KeyRound, label: 'Secrets' },
    { to: `${basePath}/environments`, icon: GitBranch, label: 'Environments' },
    { to: `${basePath}/team`, icon: Users, label: 'Team' },
    { to: `${basePath}/tokens`, icon: Ticket, label: 'Tokens' },
    ...(isOwner ? [{ to: `${basePath}/audit`, icon: ScrollText, label: 'Audit Log' }] : []),
    { to: `${basePath}/settings`, icon: Settings, label: 'Settings' },
  ];

  return (
    <aside className="sidebar">
      <nav className="sidebar-nav">
        {links.map((link) => (
          <NavLink
            key={link.to}
            to={link.to}
            className={({ isActive }) => `sidebar-link ${isActive ? 'sidebar-link-active' : ''}`}
          >
            <link.icon size={16} />
            <span>{link.label}</span>
          </NavLink>
        ))}
      </nav>
    </aside>
  );
}
