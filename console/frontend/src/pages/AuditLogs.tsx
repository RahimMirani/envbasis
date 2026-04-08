import { useEffect, useMemo, useState } from 'react';
import {
  ArrowDownToLine,
  CirclePlus,
  ShieldAlert,
  UserCheck,
  Server,
  KeyRound,
  FolderKanban,
  Activity,
  LucideIcon,
  X,
} from 'lucide-react';
import { useOutletContext } from 'react-router-dom';
import DashboardLoader from '../components/DashboardLoader';
import { useAuth } from '../auth/useAuth';
import { listUnifiedAuditLogs, downloadAuditLogs } from '../lib/api';
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

interface DateGroup {
  label: string;
  key: string;
  logs: AuditLog[];
}

function groupLogsByDate(logs: AuditLog[]): DateGroup[] {
  const groups: DateGroup[] = [];
  const today = new Date();
  const yesterday = new Date(today);
  yesterday.setDate(yesterday.getDate() - 1);

  const todayStr = today.toDateString();
  const yesterdayStr = yesterday.toDateString();

  for (const log of logs) {
    const logDate = new Date(log.created_at);
    const logDateStr = logDate.toDateString();

    let label: string;
    if (logDateStr === todayStr) {
      label = 'Today';
    } else if (logDateStr === yesterdayStr) {
      label = 'Yesterday';
    } else {
      label = logDate.toLocaleDateString('en-US', {
        month: 'long',
        day: 'numeric',
        ...(logDate.getFullYear() !== today.getFullYear() ? { year: 'numeric' } : {}),
      });
    }

    const existing = groups.find((g) => g.key === logDateStr);
    if (existing) {
      existing.logs.push(log);
    } else {
      groups.push({ label, key: logDateStr, logs: [log] });
    }
  }

  return groups;
}

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
  const [isExporting, setIsExporting] = useState(false);

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

  const dateGroups = useMemo(() => groupLogsByDate(filteredLogs), [filteredLogs]);

  const uniqueActions = useMemo(() => [...new Set(logs.map((log) => log.action))], [logs]);
  const actionOptions = useMemo(
    () => [
      { value: 'all', label: 'All actions' },
      ...uniqueActions.map((action) => ({
        value: action,
        label: getAuditActionLabel(action),
      })),
    ],
    [uniqueActions]
  );
  const environmentOptions = useMemo(
    () => [
      { value: 'all', label: 'All environments' },
      ...[...new Set(logs.map((log) => log.environment_name).filter(Boolean))].map(
        (environmentName) => ({
          value: environmentName!,
          label: environmentName!,
        })
      ),
    ],
    [logs]
  );

  const sourceOptions = [
    { value: 'all', label: 'All' },
    { value: 'project', label: 'Project' },
    { value: 'cli_auth', label: 'CLI Auth' },
  ] as const;

  const hasActiveFilters = filterAction !== 'all' || filterEnv !== 'all';

  const handleClearFilters = () => {
    setFilterAction('all');
    setFilterEnv(currentEnv === 'all' ? 'all' : currentEnv);
  };

  const handleExport = async (format: 'csv' | 'json') => {
    if (!accessToken || isExporting) return;
    setIsExporting(true);
    try {
      await downloadAuditLogs(currentProject.id, accessToken, format);
    } catch (exportError) {
      setError((exportError as Error).message || 'Export failed.');
    } finally {
      setIsExporting(false);
    }
  };

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
        <div className="page-header-actions">
          <button
            className="btn btn-secondary btn-sm"
            onClick={() => { void handleExport('csv'); }}
            disabled={isExporting || logs.length === 0}
            title="Export as CSV"
          >
            <ArrowDownToLine size={13} />
            {isExporting ? 'Exporting…' : 'Export CSV'}
          </button>
          <button
            className="btn btn-secondary btn-sm"
            onClick={() => { void handleExport('json'); }}
            disabled={isExporting || logs.length === 0}
            title="Export as JSON"
          >
            <ArrowDownToLine size={13} />
            Export JSON
          </button>
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
          <div className="audit-filter-bar">
            <div className="audit-source-pills">
              {sourceOptions.map((option) => (
                <button
                  key={option.value}
                  className={`audit-source-pill${filterSource === option.value ? ' audit-source-pill-active' : ''}`}
                  onClick={() =>
                    setFilterSource(option.value as 'all' | 'project' | 'cli_auth')
                  }
                >
                  {option.label}
                </button>
              ))}
            </div>

            <div className="audit-filter-divider" />

            <select
              className="input select audit-filter-select-compact"
              value={filterAction}
              onChange={(event) => setFilterAction(event.target.value)}
              aria-label="Filter by action"
            >
              {actionOptions.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>

            <select
              className="input select audit-filter-select-compact"
              value={filterEnv}
              onChange={(event) => setFilterEnv(event.target.value)}
              disabled={filterSource === 'cli_auth'}
              aria-label="Filter by environment"
            >
              {environmentOptions.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>

            {hasActiveFilters && (
              <button className="audit-clear-btn" onClick={handleClearFilters}>
                <X size={11} />
                Clear
              </button>
            )}

            <span className="audit-count">
              {filteredLogs.length} event{filteredLogs.length !== 1 ? 's' : ''}
            </span>
          </div>

          {filteredLogs.length === 0 ? (
            <div className="empty-state">
              <h3>No matching events</h3>
              <p>Try adjusting your filters to see more results.</p>
            </div>
          ) : (
            <div className="card">
              <div className="audit-timeline">
                {dateGroups.map((group) => (
                  <div key={group.key} className="audit-date-group">
                    <div className="audit-date-header">{group.label}</div>
                    {group.logs.map((log) => {
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
                              <span className="audit-event-action">
                                {getAuditActionLabel(log.action)}
                              </span>
                              <span
                                className={`badge ${log.source === 'cli_auth' ? 'badge-info' : 'badge-neutral'}`}
                              >
                                {log.source === 'cli_auth' ? 'CLI Auth' : 'Project'}
                              </span>
                              {log.environment_name && (
                                <span
                                  className={`badge badge-env badge-env-${log.environment_name}`}
                                >
                                  {log.environment_name}
                                </span>
                              )}
                              <span
                                className="audit-event-time"
                                title={new Date(log.created_at).toLocaleString()}
                              >
                                {formatRelativeTime(log.created_at)}
                              </span>
                            </div>
                            {details && (
                              <div className="audit-event-meta">
                                <span className="audit-event-details">{details}</span>
                              </div>
                            )}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                ))}
              </div>
              {nextCursor && (
                <div className="audit-load-more">
                  <button
                    className="btn btn-secondary btn-sm"
                    onClick={handleLoadMore}
                    disabled={isLoadingMore}
                  >
                    {isLoadingMore ? 'Loading…' : 'Load more'}
                  </button>
                </div>
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
}
