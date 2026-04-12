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
import SectionLoader from '../components/SectionLoader';
import { useAuth } from '../auth/useAuth';
import { listAuditLogs, downloadAuditLogs } from '../lib/api';
import {
  getAuditActionLabel,
  getAuditColor,
  getAuditDetails,
  getAuditIconKey,
} from '../lib/audit';
import { formatRelativeTime } from '../lib/format';
import type { ProjectPageCacheApi } from '../lib/projectPageCache';
import { getUserDisplayName } from '../lib/user';
import type { Project, AuditLog } from '../types/api';

interface OutletContextType {
  currentProject: Project;
  currentEnv: string;
  pageCache: ProjectPageCacheApi;
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
  const { currentProject, currentEnv, pageCache } = useOutletContext<OutletContextType>();
  const { accessToken, apiConfigError } = useAuth();
  const auditCacheKey = `audit:${currentProject.id}`;
  const cachedLogs = pageCache.get<AuditLog[]>(auditCacheKey);
  const [logs, setLogs] = useState<AuditLog[]>(() => cachedLogs ?? []);
  const [isLoading, setIsLoading] = useState(() => !cachedLogs);
  const [error, setError] = useState<string | null>(null);
  const [filterAction, setFilterAction] = useState('all');
  const [filterEnv, setFilterEnv] = useState(currentEnv === 'all' ? 'all' : currentEnv);
  const [isExporting, setIsExporting] = useState(false);

  if (!currentProject.can_view_audit_logs) {
    return (
      <div className="empty-state">
        <h3>Audit logs are restricted</h3>
        <p>The project owner has not enabled audit log visibility for members.</p>
      </div>
    );
  }

  useEffect(() => {
    setFilterEnv(currentEnv === 'all' ? 'all' : currentEnv);
  }, [currentEnv]);

  useEffect(() => {
    if (!accessToken) return undefined;

    if (apiConfigError) {
      setError(apiConfigError);
      setIsLoading(false);
      return undefined;
    }

    let isActive = true;
    const controller = new AbortController();

    async function loadAuditLogs() {
      if (cachedLogs) {
        setIsLoading(false);
        return;
      }

      setIsLoading(true);
      setError(null);
      try {
        const response = await listAuditLogs(currentProject.id, accessToken!, {
          limit: 500,
          signal: controller.signal,
        });
        if (!isActive) return;
        setLogs(response);
        pageCache.set<AuditLog[]>(auditCacheKey, response);
      } catch (loadError) {
        if (!isActive || controller.signal.aborted) return;
        setError((loadError as Error).message || 'Failed to load audit logs.');
        setLogs([]);
      } finally {
        if (isActive) setIsLoading(false);
      }
    }

    void loadAuditLogs();
    return () => { isActive = false; controller.abort(); };
  }, [accessToken, apiConfigError, auditCacheKey, cachedLogs, currentProject.id, pageCache]);

  const filteredLogs = useMemo(
    () =>
      logs.filter((log) => {
        const matchAction = filterAction === 'all' || log.action === filterAction;
        const matchEnv =
          filterEnv === 'all' || (log.environment_name ?? '—') === filterEnv;
        return matchAction && matchEnv;
      }),
    [filterAction, filterEnv, logs]
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
        (environmentName) => ({ value: environmentName!, label: environmentName! })
      ),
    ],
    [logs]
  );

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

  return (
    <div className="audit-page animate-in">
      <div className="page-header">
        <div>
          <h1 className="page-heading">Audit Logs</h1>
          <p className="page-subtitle">
            A record of all actions taken in this project.
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
        <SectionLoader label="Loading audit logs" />
      ) : logs.length === 0 ? (
        <div className="empty-state">
          <h3>No audit events yet</h3>
          <p>Audit entries will appear as actions are taken in this project.</p>
        </div>
      ) : (
        <>
          <div className="audit-filter-bar">
            <select
              className="input select audit-filter-select-compact"
              value={filterAction}
              onChange={(e) => setFilterAction(e.target.value)}
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
              onChange={(e) => setFilterEnv(e.target.value)}
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
            </div>
          )}
        </>
      )}
    </div>
  );
}
