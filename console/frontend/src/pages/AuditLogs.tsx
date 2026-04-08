import { useEffect, useMemo, useState } from 'react';
import {
  Filter,
  ArrowDownToLine,
  CirclePlus,
  ShieldAlert,
  UserCheck,
  Server,
  KeyRound,
  FolderKanban,
  Activity,
  LucideIcon,
} from 'lucide-react';
import { useOutletContext } from 'react-router-dom';
import DashboardLoader from '../components/DashboardLoader';
import { useAuth } from '../auth/useAuth';
import { listUnifiedAuditLogs } from '../lib/api';
import {
  getAuditActionLabel,
  getAuditColor,
  getAuditDetails,
  getAuditIconKey,
} from '../lib/audit';
import { formatRelativeTime } from '../lib/format';
import { getUserDisplayName } from '../lib/user';
import type { Project, AuditLog } from '../types/api';

interface OutletContextType {
  currentProject: Project;
  currentEnv: string;
}

const auditIcons: Record<string, LucideIcon> = {
  key: KeyRound,
  pull: ArrowDownToLine,
  token: CirclePlus,
  revoke: ShieldAlert,
  member: UserCheck,
  environment: Server,
  project: FolderKanban,
  activity: Activity,
};

export default function AuditLogsPage() {
  const { currentProject, currentEnv } = useOutletContext<OutletContextType>();
  const { accessToken, apiConfigError } = useAuth();
  const [logs, setLogs] = useState<AuditLog[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isLoadingMore, setIsLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [filterAction, setFilterAction] = useState('all');
  const [filterEnv, setFilterEnv] = useState(currentEnv === 'all' ? 'all' : currentEnv);
  const [filterSource, setFilterSource] = useState<'all' | 'project' | 'cli_auth'>('all');
  const [nextCursor, setNextCursor] = useState<string | null>(null);

  useEffect(() => {
    setFilterEnv(currentEnv === 'all' ? 'all' : currentEnv);
  }, [currentEnv]);

  useEffect(() => {
    if (!accessToken) {
      return undefined;
    }

    if (apiConfigError) {
      setError(apiConfigError);
      setIsLoading(false);
      return undefined;
    }

    let isActive = true;
    const controller = new AbortController();

    async function loadAuditLogs() {
      setIsLoading(true);
      setError(null);

      try {
        const response = await listUnifiedAuditLogs(accessToken!, {
          limit: 50,
          projectId: currentProject.id,
          source: filterSource,
          signal: controller.signal,
        });

        if (!isActive) {
          return;
        }

        setLogs(response.logs);
        setNextCursor(response.next_cursor);
      } catch (loadError) {
        if (!isActive || controller.signal.aborted) {
          return;
        }

        setError((loadError as Error).message || 'Failed to load audit logs.');
        setLogs([]);
        setNextCursor(null);
      } finally {
        if (isActive) {
          setIsLoading(false);
        }
      }
    }

    void loadAuditLogs();

    return () => {
      isActive = false;
      controller.abort();
    };
  }, [accessToken, apiConfigError, currentProject.id, filterSource]);

  const filteredLogs = useMemo(
    () =>
      logs.filter((log) => {
        const matchAction = filterAction === 'all' || log.action === filterAction;
        const environmentName = log.environment_name || '—';
        const matchEnv =
          filterEnv === 'all' ||
          (filterSource === 'cli_auth' ? true : environmentName === filterEnv) ||
          (log.source === 'cli_auth' && filterEnv === 'all');
        return matchAction && matchEnv;
      }),
    [filterAction, filterEnv, filterSource, logs]
  );

  const uniqueActions = useMemo(() => [...new Set(logs.map((log) => log.action))], [logs]);

  const sourceOptions = [
    { value: 'all', label: 'All sources' },
    { value: 'project', label: 'Project' },
    { value: 'cli_auth', label: 'CLI auth' },
  ] as const;

  const handleLoadMore = async () => {
    if (!accessToken || !nextCursor || isLoadingMore) {
      return;
    }

    setIsLoadingMore(true);
    setError(null);

    try {
      const response = await listUnifiedAuditLogs(accessToken, {
        limit: 50,
        cursor: nextCursor,
        projectId: currentProject.id,
        source: filterSource,
      });
      setLogs((currentLogs) => [...currentLogs, ...response.logs]);
      setNextCursor(response.next_cursor);
    } catch (loadError) {
      setError((loadError as Error).message || 'Failed to load more audit logs.');
    } finally {
      setIsLoadingMore(false);
    }
  };

  return (
    <div className="audit-page animate-in">
      <div className="page-header">
        <div>
          <h1 className="page-heading">Audit Logs</h1>
          <p className="page-subtitle">
            A combined feed of this project&apos;s activity and your CLI authentication events.
          </p>
        </div>
      </div>

      {error && (
        <div className="auth-status auth-status-error" role="alert">
          <span>{error}</span>
        </div>
      )}

      {isLoading ? (
        <DashboardLoader
          compact
          title="Loading audit logs"
          description="Fetching the combined project and CLI activity trail."
        />
      ) : logs.length === 0 ? (
        <div className="empty-state">
          <h3>No audit events yet</h3>
          <p>
            Audit entries will appear as project actions happen and CLI logins are approved or
            denied.
          </p>
        </div>
      ) : (
        <>
          <div className="audit-filters">
            <select
              className="input select audit-filter-select"
              value={filterSource}
              onChange={(event) =>
                setFilterSource(event.target.value as 'all' | 'project' | 'cli_auth')
              }
              id="audit-filter-source"
            >
              {sourceOptions.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
            <div className="audit-filter-group">
              <Filter size={14} className="audit-filter-icon" />
              <select
                className="input select audit-filter-select"
                value={filterAction}
                onChange={(event) => setFilterAction(event.target.value)}
                id="audit-filter-action"
              >
                <option value="all">All actions</option>
                {uniqueActions.map((action) => (
                  <option key={action} value={action}>
                    {getAuditActionLabel(action)}
                  </option>
                ))}
              </select>
            </div>
            <select
              className="input select audit-filter-select"
              value={filterEnv}
              onChange={(event) => setFilterEnv(event.target.value)}
              id="audit-filter-env"
              disabled={filterSource === 'cli_auth'}
            >
              <option value="all">All environments</option>
              {[...new Set(logs.map((log) => log.environment_name).filter(Boolean))].map(
                (environmentName) => (
                  <option key={environmentName} value={environmentName!}>
                    {environmentName}
                  </option>
                )
              )}
            </select>
            <span className="audit-count">
              {filteredLogs.length} event{filteredLogs.length !== 1 ? 's' : ''}
            </span>
          </div>

          <div className="card">
            <div className="audit-timeline">
              {filteredLogs.map((log) => {
                const iconKey = getAuditIconKey(log.action);
                const Icon = auditIcons[iconKey] || Activity;
                const color = getAuditColor(log.action);
                const details = getAuditDetails(log);

                return (
                  <div className="audit-event" key={log.id}>
                    <div className={`audit-event-icon activity-icon-${color}`}>
                      <Icon size={14} />
                    </div>
                    <div className="audit-event-content">
                      <div className="audit-event-main">
                        <span className="audit-event-actor">
                          {getUserDisplayName({ email: log.actor_email })}
                        </span>
                        <span className="audit-event-action">{getAuditActionLabel(log.action)}</span>
                        <span
                          className={`badge ${log.source === 'cli_auth' ? 'badge-info' : 'badge-neutral'}`}
                        >
                          {log.source === 'cli_auth' ? 'CLI Auth' : 'Project'}
                        </span>
                        {log.environment_name && (
                          <span className={`badge badge-env badge-env-${log.environment_name}`}>
                            {log.environment_name}
                          </span>
                        )}
                      </div>
                      <div className="audit-event-meta">
                        <span className="audit-event-details">
                          {details || 'No additional details.'}
                        </span>
                        <span className="audit-event-time">
                          {formatRelativeTime(log.created_at)}
                        </span>
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
            {nextCursor && (
              <div style={{ display: 'flex', justifyContent: 'center', padding: '1rem 1.25rem 1.25rem' }}>
                <button className="btn btn-secondary btn-sm" onClick={handleLoadMore} disabled={isLoadingMore}>
                  {isLoadingMore ? 'Loading...' : 'Load More'}
                </button>
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}
