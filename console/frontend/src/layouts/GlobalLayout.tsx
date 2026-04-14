import { useState } from 'react';
import { Outlet } from 'react-router-dom';
import { Menu } from 'lucide-react';
import GlobalSidebar from '../components/GlobalSidebar';

export default function GlobalLayout() {
  const [sidebarOpen, setSidebarOpen] = useState(false);

  return (
    <div className="global-layout">
      <header className="global-mobile-topbar">
        <button
          className="topbar-hamburger"
          onClick={() => setSidebarOpen(true)}
          aria-label="Open navigation"
        >
          <Menu size={20} />
        </button>
        <span className="global-mobile-topbar-logo">envbasis</span>
      </header>
      <div
        className={`sidebar-backdrop${sidebarOpen ? ' sidebar-open' : ''}`}
        onClick={() => setSidebarOpen(false)}
      />
      <GlobalSidebar open={sidebarOpen} onClose={() => setSidebarOpen(false)} />
      <main className="global-layout-main">
        <Outlet />
      </main>
    </div>
  );
}
