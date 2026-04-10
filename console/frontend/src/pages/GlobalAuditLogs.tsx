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
  X,
  type LucideIcon,
} from 'lucide-react';
import SectionLoader from '../components/SectionLoader';
import { useAuth } from '../auth/useAuth';
import { listUnifiedAuditLogs, listProjects } from '../lib/api';
import {
  getAuditActionLabel,
  getAuditColor,
  getAuditDetails,
  getAuditIconKey,
} from '../lib/audit';
import { formatRelativeTime } from '../lib/format';
import { getUserDisplayName } from '../lib/user';
import type { AuditLog, Project } from '../types/api';

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

const sourceOptions = [
  { value: 'all', label: 'All sources' },
  { value: 'project', label: 'Project activity' },
  { value: 'cli_auth', label: 'CLI Auth' },
] as const;

export default function GlobalAuditLogsPage() {
  const { accessToken, apiConfigError } = useAuth();
  const [projects, setProjects] = useState<Project[]>([]);
  const [logs, setLogs] = useState<AuditLog[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isLoadingMore, setIsLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [filterProject, setFilterProject] = useState<string>('all');
  const [filterAction, setFilterAction] = useState('all');
  const [filterSource, setFilterSource] = useState<'all' | 'project' | 'cli_auth'>('all');
  const [nextCursor, setNextCursor] = useState<string | null>(null);

  // Load project list once for the project filter dropdown
  useEffect(() => {
    if (!accessToken || apiConfigError) return;
    listProjects(accessToken).then(setProjects).catch(() => {});
  }, [accessToken, apiConfigError]);

  // Re-fetch logs whenever project or source filter changes
  useEffect(() => {
    if (!accessToken) return undefined;
    if (apiConfigError) {
      setError(apiConfigError);
      setIsLoading(false);
      return undefined;
    }

    let isActive = true;
    const controller = new AbortController();

    async function load() {
      setIsLoading(true);
      setError(null);
      setFilterAction('all');
      try {
        const response = await listUnifiedAuditLogs(accessToken!, {
          limit: 50,
          projectId: filterProject === 'all' ? undefined : filterProject,
          source: filterSource,
          signal: controller.signal,
        });
        if (!isActive) return;
        setLogs(response.logs);
        setNextCursor(response.next_cursor);
      } catch (err) {
        if (!isActive || controller.signal.aborted) return;
        setError((err as Error).message || 'Failed to load audit logs.');
        setLogs([]);
        setNextCursor(null);
      } finally {
        if (isActive) setIsLoading(false);
      }
    }

    void load();
    return () => { isActive = false; controller.abort(); };
  }, [accessToken, apiConfigError, filterProject, filterSource]);

  const filteredLogs = useMemo(
    () => logs.filter((log) => filterAction === 'all' || log.action === filterAction),
    [filterAction, logs]
  );

  const dateGroups = useMemo(() => groupLogsByDate(filteredLogs), [filteredLogs]);

  const uniqueActions = useMemo(() => [...new Set(logs.map((log) => log.action))], [logs]);
  const actionOptions = useMemo(
    () => [
      { value: 'all', label: 'All actions' },
      ...uniqueActions.map((action) => ({ value: action, label: getAuditActionLabel(action) })),
    ],
    [uniqueActions]
  );

  const selectedProject = projects.find((p) => p.id === filterProject);
  const hasActiveFilters = filterAction !== 'all';

  const handleLoadMore = async () => {
    if (!accessToken || !nextCursor || isLoadingMore) return;
    setIsLoadingMore(true);
    try {
      const response = await listUnifiedAuditLogs(accessToken, {
        limit: 50,
        cursor: nextCursor,
        projectId: filterProject === 'all' ? undefined : filterProject,
        source: filterSource,
      });
      setLogs((current) => [...current, ...response.logs]);
      setNextCursor(response.next_cursor);
    } catch (err) {
      setError((err as Error).message || 'Failed to load more audit logs.');
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
            {selectedProject
              ? `Showing activity for ${selectedProject.name}.`
              : 'Unified activity feed across all your projects and CLI authentication events.'}
          </p>
        </div>
      </div>

      {error && (
        <div className="auth-status auth-status-error" role="alert">
          <span>{error}</span>
        </div>
      )}

      {/* Project selector — always visible */}
      {projects.length > 0 && (
        <div className="audit-project-bar">
          <span className="audit-project-bar-label">Project</span>
          <button
            className={`audit-project-pill${filterProject === 'all' ? ' audit-project-pill-active' : ''}`}
            onClick={() => setFilterProject('all')}
          >
            All
          </button>
          {projects.map((p) => (
            <button
              key={p.id}
              className={`audit-project-pill${filterProject === p.id ? ' audit-project-pill-active' : ''}`}
              onClick={() => setFilterProject(p.id)}
            >
              {p.name}
            </button>
          ))}
        </div>
      )}

      {isLoading ? (
        <SectionLoader label="Loading audit logs" />
      ) : logs.length === 0 ? (
        <div className="empty-state">
          <h3>No audit events yet</h3>
          <p>Audit entries will appear as project actions happen and CLI logins are approved or denied.</p>
        </div>
      ) : (
        <>
          <div className="audit-filter-bar">
            <select
              className="input select audit-filter-select-compact"
              value={filterSource}
              onChange={(e) => setFilterSource(e.target.value as 'all' | 'project' | 'cli_auth')}
              aria-label="Filter by source"
            >
              {sourceOptions.map((option) => (
                <option key={option.value} value={option.value}>{option.label}</option>
              ))}
            </select>

            <div className="audit-filter-divider" />

            <select
              className="input select audit-filter-select-compact"
              value={filterAction}
              onChange={(e) => setFilterAction(e.target.value)}
              aria-label="Filter by action"
            >
              {actionOptions.map((option) => (
                <option key={option.value} value={option.value}>{option.label}</option>
              ))}
            </select>

            {hasActiveFilters && (
              <button className="audit-clear-btn" onClick={() => setFilterAction('all')}>
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
                              <span className={`badge ${log.source === 'cli_auth' ? 'badge-info' : 'badge-neutral'}`}>
                                {log.source === 'cli_auth' ? 'CLI Auth' : 'Project'}
                              </span>
                              {log.environment_name && (
                                <span className={`badge badge-env badge-env-${log.environment_name}`}>
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
                    onClick={() => { void handleLoadMore(); }}
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
