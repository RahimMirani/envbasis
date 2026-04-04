import { useEffect, useMemo, useState } from 'react';
import { useNavigate, useOutletContext } from 'react-router-dom';
import {
  KeyRound,
  GitBranch,
  Users,
  Ticket,
  ArrowUpRight,
  UserPlus,
  Terminal,
  CheckCircle2,
  ArrowDownToLine,
  CirclePlus,
  ShieldAlert,
  UserCheck,
  Server,
  FolderKanban,
  Activity,
  LucideIcon,
} from 'lucide-react';
import CodeBlock from '../components/CodeBlock';
import DashboardLoader from '../components/DashboardLoader';
import { useAuth } from '../auth/useAuth';
import { listAuditLogs } from '../lib/api';
import {
  getAuditActionLabel,
  getAuditColor,
  getAuditDetails,
  getAuditIconKey,
} from '../lib/audit';
import { formatRelativeTime } from '../lib/format';
import { getUserDisplayName } from '../lib/user';
import type { Project, Environment, AuditLog, SecretStats } from '../types/api';

interface OutletContextType {
  currentProject: Project;
  projectBasePath: string;
  environments: Environment[];
  currentEnv: string;
  canManageProject: boolean;
  secretStats: SecretStats | null;
  isSecretStatsLoading: boolean;
}

const activityIcons: Record<string, LucideIcon> = {
  key: KeyRound,
  pull: ArrowDownToLine,
  token: CirclePlus,
  revoke: ShieldAlert,
  member: UserCheck,
  environment: Server,
  project: FolderKanban,
  activity: Activity,
};

export default function OverviewPage() {
  const {
    currentProject,
    projectBasePath,
    environments,
    currentEnv,
    canManageProject,
    secretStats,
    isSecretStatsLoading,
  } = useOutletContext<OutletContextType>();
  const { accessToken, apiConfigError } = useAuth();
  const navigate = useNavigate();
  const [activityLogs, setActivityLogs] = useState<AuditLog[]>([]);
  const [isLoading, setIsLoading] = useState(true);

  const totalSecretCount = secretStats?.total_secret_count;

  useEffect(() => {
    if (!accessToken || apiConfigError) {
      setIsLoading(false);
      return undefined;
    }

    let isActive = true;
    const controller = new AbortController();

    async function loadOverviewData() {
      setIsLoading(true);

      try {
        if (currentProject.role === 'owner') {
          const logs = await listAuditLogs(currentProject.id, accessToken!, {
            limit: 6,
            signal: controller.signal,
          });

          if (isActive) {
            setActivityLogs(logs);
          }
        } else if (isActive) {
          setActivityLogs([]);
        }
      } catch {
        if (isActive) {
          setActivityLogs([]);
        }
      } finally {
        if (isActive) {
          setIsLoading(false);
        }
      }
    }

    void loadOverviewData();

    return () => {
      isActive = false;
      controller.abort();
    };
  }, [accessToken, apiConfigError, currentProject.id, currentProject.role]);

  const stats = [
    {
      label: 'Secrets',
      value: isSecretStatsLoading ? '...' : totalSecretCount ?? '—',
      icon: KeyRound,
      color: 'accent',
    },
    {
      label: 'Environments',
      value: currentProject.environment_count || 0,
      icon: GitBranch,
      color: 'success',
    },
    { label: 'Members', value: currentProject.member_count || 0, icon: Users, color: 'info' },
    {
      label: 'Active Tokens',
      value: currentProject.runtime_token_count || 0,
      icon: Ticket,
      color: 'warning',
    },
  ];

  const onboardingChecklist = useMemo(
    () => [
      {
        id: 'ob1',
        label: 'Create first environment',
        done: (currentProject.environment_count || 0) > 0,
      },
      {
        id: 'ob2',
        label: 'Create runtime token',
        done: (currentProject.runtime_token_count || 0) > 0,
      },
      {
        id: 'ob3',
        label: 'Invite your first teammate',
        done: (currentProject.member_count || 0) > 1,
      },
    ],
    [
      currentProject.environment_count,
      currentProject.member_count,
      currentProject.runtime_token_count,
    ]
  );

  const allDone = onboardingChecklist.every((item) => item.done);
  const cliEnvironmentName =
    currentEnv === 'all' ? environments[0]?.name || 'dev' : currentEnv;

  return (
    <div className="overview-page animate-in">
      <div className="overview-hero">
        <div className="overview-hero-left">
          <h1 className="overview-project-name mono">{currentProject.name}</h1>
          <p className="overview-project-desc">
            {currentProject.description || 'No description yet.'}
          </p>
        </div>
        <div className="overview-hero-actions">
          <button
            className="btn btn-secondary"
            onClick={() => navigate(`${projectBasePath}/tokens`)}
            id="quick-create-token"
            disabled={!canManageProject}
          >
            <Ticket size={14} />
            Create Token
          </button>
          <button
            className="btn btn-secondary"
            onClick={() => navigate(`${projectBasePath}/team`)}
            id="quick-invite"
            disabled={!canManageProject}
          >
            <UserPlus size={14} />
            Invite
          </button>
          <button
            className="btn btn-primary"
            onClick={() => navigate(`${projectBasePath}/secrets`)}
            id="quick-view-secrets"
          >
            <KeyRound size={14} />
            View Secrets
          </button>
        </div>
      </div>

      <div className="overview-stats stagger-in">
        {stats.map((stat) => (
          <div className="card stat-card" key={stat.label}>
            <div className="stat-card-header">
              <div className={`stat-card-icon stat-card-icon-${stat.color}`}>
                <stat.icon size={16} strokeWidth={2} />
              </div>
            </div>
            <div className="stat-card-value">{stat.value}</div>
            <div className="stat-card-label">{stat.label}</div>
          </div>
        ))}
      </div>

      <div className={`overview-grid ${currentProject.role !== 'owner' ? 'overview-grid-member' : ''}`}>
        {currentProject.role === 'owner' && (
          <div className="overview-section">
            <div className="overview-section-header">
              <h3>Recent Activity</h3>
              <button
                className="btn btn-ghost btn-sm"
                onClick={() => navigate(`${projectBasePath}/audit`)}
              >
                View All <ArrowUpRight size={12} />
              </button>
            </div>
            <div className="card">
              {isLoading ? (
                <DashboardLoader
                  compact
                  title="Loading activity"
                  description="Fetching recent project actions."
                />
              ) : activityLogs.length === 0 ? (
                <div className="empty-state">
                  <h3>No activity yet</h3>
                  <p>Actions will appear here as the project changes.</p>
                </div>
              ) : (
                <div className="activity-list">
                  {activityLogs.map((log) => {
                    const iconKey = getAuditIconKey(log.action);
                    const Icon = activityIcons[iconKey] || Terminal;
                    return (
                      <div className="activity-item" key={log.id}>
                        <div
                          className={`activity-icon activity-icon-${getAuditColor(log.action)}`}
                        >
                          <Icon size={14} />
                        </div>
                        <div className="activity-content">
                          <span className="activity-text">
                            {getUserDisplayName({ email: log.actor_email })}{' '}
                            {getAuditActionLabel(log.action)}
                          </span>
                          <span className="activity-time">
                            {getAuditDetails(log) || formatRelativeTime(log.created_at)}
                          </span>
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          </div>
        )}

        <div className="overview-right-col">
          {!allDone && (
            <div className="overview-section">
              <div className="overview-section-header">
                <h3>Getting Started</h3>
              </div>
              <div className="card onboarding-card">
                <div className="onboarding-progress">
                  <div className="onboarding-progress-bar">
                    <div
                      className="onboarding-progress-fill"
                      style={{
                        width: `${(onboardingChecklist.filter((item) => item.done).length / onboardingChecklist.length) * 100}%`,
                      }}
                    />
                  </div>
                  <span className="onboarding-progress-text">
                    {onboardingChecklist.filter((item) => item.done).length}/
                    {onboardingChecklist.length} complete
                  </span>
                </div>
                <div className="onboarding-list">
                  {onboardingChecklist.map((item) => (
                    <div
                      className={`onboarding-item ${item.done ? 'onboarding-item-done' : ''}`}
                      key={item.id}
                    >
                      <CheckCircle2 size={16} />
                      <span>{item.label}</span>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )}

          {currentProject.role !== 'owner' && (
            <div className="overview-section">
              <div className="overview-section-header">
                <h3>Access</h3>
              </div>
              <div className="card onboarding-card">
                <div className="onboarding-list">
                  <div className="onboarding-item">
                    <CheckCircle2 size={16} />
                    <span>You can view project metadata and any resources shared with you.</span>
                  </div>
                  <div className="onboarding-item">
                    <CheckCircle2 size={16} />
                    <span>Project audit logs remain visible to owners only.</span>
                  </div>
                </div>
              </div>
            </div>
          )}

          <div className="overview-section">
            <div className="overview-section-header">
              <h3>
                <Terminal size={16} style={{ verticalAlign: 'text-bottom', marginRight: 6 }} />
                CLI Quickstart
              </h3>
            </div>
            <div className="card cli-card">
              <p className="cli-desc">Get started with EnvBasis CLI in your terminal.</p>
              <CodeBlock
                commands={[
                  { cmd: 'envbasis', args: 'login' },
                  { cmd: 'envbasis', args: `env use ${cliEnvironmentName}` },
                  { cmd: 'envbasis', args: 'pull --file .env' },
                  { cmd: 'envbasis', args: 'push --file .env' },
                ]}
              />
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
