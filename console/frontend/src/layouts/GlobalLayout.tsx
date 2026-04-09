import { Outlet } from 'react-router-dom';
import GlobalSidebar from '../components/GlobalSidebar';

export default function GlobalLayout() {
  return (
    <div className="global-layout">
      <GlobalSidebar />
      <main className="global-layout-main">
        <Outlet />
      </main>
    </div>
  );
}
