import { lazy, Suspense } from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import RequireAuth from './components/RequireAuth';
import SectionLoader from './components/SectionLoader';
import GlobalLayout from './layouts/GlobalLayout';
import ProjectLayout from './layouts/ProjectLayout';

const LoginPage = lazy(() => import('./pages/Login'));
const SignupPage = lazy(() => import('./pages/Signup'));
const AuthCallbackPage = lazy(() => import('./pages/AuthCallback'));
const CliAuthPage = lazy(() => import('./pages/CliAuth'));
const ProjectsPage = lazy(() => import('./pages/Projects'));
const GlobalAuditLogsPage = lazy(() => import('./pages/GlobalAuditLogs'));
const AccountSettingsPage = lazy(() => import('./pages/AccountSettings'));
const OverviewPage = lazy(() => import('./pages/Overview'));
const SecretsPage = lazy(() => import('./pages/Secrets'));
const EnvironmentsPage = lazy(() => import('./pages/Environments'));
const TeamPage = lazy(() => import('./pages/Team'));
const MachineIdentitiesPage = lazy(() => import('./pages/MachineIdentities'));
const AuditLogsPage = lazy(() => import('./pages/AuditLogs'));
const SettingsPage = lazy(() => import('./pages/Settings'));
const GovernancePage = lazy(() => import('./pages/Governance'));

export default function App() {
  return (
    <BrowserRouter>
      <Suspense
        fallback={
          <div className="project-layout-loading">
            <SectionLoader label="Loading page" />
          </div>
        }
      >
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/signup" element={<SignupPage />} />
          <Route path="/auth/callback" element={<AuthCallbackPage />} />
          <Route
            path="/cli/auth"
            element={
              <RequireAuth>
                <CliAuthPage />
              </RequireAuth>
            }
          />
          <Route
            element={
              <RequireAuth>
                <GlobalLayout />
              </RequireAuth>
            }
          >
            <Route path="/" element={<ProjectsPage />} />
            <Route path="/audit" element={<GlobalAuditLogsPage />} />
            <Route path="/account" element={<AccountSettingsPage />} />
          </Route>
          <Route
            path="/projects/:projectId"
            element={
              <RequireAuth>
                <ProjectLayout />
              </RequireAuth>
            }
          >
            <Route index element={<Navigate to="overview" replace />} />
            <Route path="overview" element={<OverviewPage />} />
            <Route path="secrets" element={<SecretsPage />} />
            <Route path="environments" element={<EnvironmentsPage />} />
            <Route path="team" element={<TeamPage />} />
            <Route path="machine-identities" element={<MachineIdentitiesPage />} />
            <Route path="tokens" element={<Navigate to="../machine-identities" replace />} />
            <Route path="audit" element={<AuditLogsPage />} />
            <Route path="governance" element={<GovernancePage />} />
            <Route path="settings" element={<SettingsPage />} />
          </Route>
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </Suspense>
    </BrowserRouter>
  );
}
