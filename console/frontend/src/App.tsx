import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import RequireAuth from './components/RequireAuth';
import GlobalLayout from './layouts/GlobalLayout';
import ProjectLayout from './layouts/ProjectLayout';
import LoginPage from './pages/Login';
import SignupPage from './pages/Signup';
import AuthCallbackPage from './pages/AuthCallback';
import CliAuthPage from './pages/CliAuth';
import ProjectsPage from './pages/Projects';
import GlobalAuditLogsPage from './pages/GlobalAuditLogs';
import AccountSettingsPage from './pages/AccountSettings';
import OverviewPage from './pages/Overview';
import SecretsPage from './pages/Secrets';
import EnvironmentsPage from './pages/Environments';
import TeamPage from './pages/Team';
import TokensPage from './pages/Tokens';
import AuditLogsPage from './pages/AuditLogs';
import SettingsPage from './pages/Settings';
import WebhooksPage from './pages/Webhooks';

export default function App() {
  return (
    <BrowserRouter>
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
          <Route path="tokens" element={<TokensPage />} />
          <Route path="audit" element={<AuditLogsPage />} />
          <Route path="webhooks" element={<WebhooksPage />} />
          <Route path="settings" element={<SettingsPage />} />
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  );
}
