import { ReactNode } from 'react';
import { Navigate, useLocation } from 'react-router-dom';
import { useAuth } from '../auth/useAuth';
import { setStoredRedirectPath } from '../auth/redirect';
import DashboardLoader from './DashboardLoader';

interface RequireAuthProps {
  children: ReactNode;
}

export default function RequireAuth({ children }: RequireAuthProps) {
  const { session, isLoading } = useAuth();
  const location = useLocation();

  if (isLoading) {
    return <DashboardLoader title="Loading session" description="Checking authentication status." />;
  }

  if (!session) {
    setStoredRedirectPath(location.pathname + location.search);
    return <Navigate to="/login" replace />;
  }

  return <>{children}</>;
}
