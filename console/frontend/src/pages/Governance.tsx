import { FormEvent, useCallback, useEffect, useMemo, useState } from 'react';
import { Navigate, useOutletContext } from 'react-router-dom';
import {
  CheckCircle2,
  ClipboardList,
  KeyRound,
  Shield,
  UserCheck,
  X,
  XCircle,
} from 'lucide-react';
import { useAuth } from '../auth/useAuth';
import SectionLoader from '../components/SectionLoader';
import Select, { envDotClass } from '../components/Select';
import {
  actOnApprovalRequest,
  createAccessAssignment,
  createAccessRole,
  createApprovalRequest,
  deleteAccessAssignment,
  listAccessAssignments,
  listAccessRoles,
  listApprovalRequests,
  listMachineIdentities,
  listMembers,
  simulatePermission,
} from '../lib/api';
import { formatRelativeTime } from '../lib/format';
import type {
  AccessRole,
  AccessRoleAssignment,
  ApprovalRequest,
  Environment,
  MachineIdentity,
  Member,
  PermissionSimulation,
  Project,
} from '../types/api';

interface OutletContextType {
  currentProject: Project;
  environments: Environment[];
  canManageProject: boolean;
}

type GovernanceTab = 'approvals' | 'roles';

function envName(environments: Environment[], environmentId: string | null | undefined): string {
  if (!environmentId) return 'All environments';
  return environments.find((environment) => environment.id === environmentId)?.name ?? 'Environment';
}

function subjectLabel(
  members: Member[],
  machines: MachineIdentity[],
  assignment: AccessRoleAssignment,
): string {
  if (assignment.user_id) {
    return members.find((member) => member.user_id === assignment.user_id)?.email ?? 'User';
  }
  if (assignment.machine_identity_id) {
    return (
      machines.find((machine) => machine.id === assignment.machine_identity_id)?.name ?? 'Machine'
    );
  }
  return 'Subject';
}

function permissionSummary(
  environments: Environment[],
  permission: AccessRole['permissions'][number],
): string {
  const action = permission.action === '*' ? 'do anything with' : permission.action;
  const resource = permission.resource === '*' ? 'all resources' : permission.resource;
  const verb = permission.effect === 'allow' ? 'Can' : 'Cannot';
  return `${verb} ${action} ${resource} · ${envName(environments, permission.environment_id)}`;
}

const SIMULATION_REASONS: Record<string, string> = {
  explicit_allow: 'an assigned role allows this',
  explicit_deny: 'an assigned role explicitly denies this',
  no_matching_permission: 'none of their assigned roles grants this',
  project_owner: 'project owners can do everything',
  member_default_read: 'project members can read by default',
  member_can_push_pull: 'this member is allowed to push and pull secrets',
  member_write_not_allowed: 'this member is not allowed to push or pull secrets',
  not_a_project_member: 'they are not a member of this project',
  machine_environment_mismatch: 'this machine is locked to a different environment',
  machine_read_only: 'machine identities are read-only',
  machine_default_read: 'this machine identity is allowed to read secrets',
  machine_cannot_read: 'this machine identity is not allowed to read secrets',
};

function approvalStatusBadge(status: string): string {
  if (status === 'pending') return 'badge-warning';
  if (status === 'approved' || status === 'applied') return 'badge-success';
  if (status === 'rejected' || status === 'cancelled' || status === 'canceled') return 'badge-danger';
  return 'badge-neutral';
}

export default function GovernancePage() {
  const { currentProject, environments, canManageProject } =
    useOutletContext<OutletContextType>();
  const { accessToken } = useAuth();
  const [roles, setRoles] = useState<AccessRole[]>([]);
  const [assignments, setAssignments] = useState<AccessRoleAssignment[]>([]);
  const [requests, setRequests] = useState<ApprovalRequest[]>([]);
  const [members, setMembers] = useState<Member[]>([]);
  const [machines, setMachines] = useState<MachineIdentity[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<GovernanceTab>('approvals');

  const [roleName, setRoleName] = useState('');
  const [resource, setResource] = useState('secrets');
  const [action, setAction] = useState('read');
  const [effect, setEffect] = useState<'allow' | 'deny'>('allow');
  const [roleEnvironment, setRoleEnvironment] = useState('');
  const rolePath = '/';
  const [assignmentDrafts, setAssignmentDrafts] = useState<Record<string, string>>({});

  const [approvalComment, setApprovalComment] = useState('');
  const [proposalEnvironment, setProposalEnvironment] = useState('');
  const proposalPath = '/';
  const [proposalKey, setProposalKey] = useState('');
  const [proposalOperation, setProposalOperation] = useState<'create' | 'update' | 'delete'>(
    'create',
  );
  const [proposalValue, setProposalValue] = useState('');

  const [simulationSubject, setSimulationSubject] = useState('');
  const [simulationResource, setSimulationResource] = useState('secrets');
  const [simulationAction, setSimulationAction] = useState('read');
  const simulationPath = '/';
  const [simulationEnvironment, setSimulationEnvironment] = useState('');
  const [simulationResult, setSimulationResult] = useState<PermissionSimulation | null>(null);

  const load = useCallback(async () => {
    if (!accessToken) return;
    setIsLoading(true);
    setError(null);
    try {
      const common = listApprovalRequests(currentProject.id, accessToken);
      if (canManageProject) {
        const [nextRoles, nextAssignments, nextRequests, nextMembers, nextMachines] =
          await Promise.all([
            listAccessRoles(currentProject.id, accessToken),
            listAccessAssignments(currentProject.id, accessToken),
            common,
            listMembers(currentProject.id, accessToken),
            listMachineIdentities(currentProject.id, accessToken),
          ]);
        setRoles(nextRoles);
        setAssignments(nextAssignments);
        setRequests(nextRequests);
        setMembers(nextMembers);
        setMachines(nextMachines);
      } else {
        setRequests(await common);
      }
    } catch (loadError) {
      setError((loadError as Error).message || 'Failed to load governance settings.');
    } finally {
      setIsLoading(false);
    }
  }, [accessToken, canManageProject, currentProject.id]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (!canManageProject && activeTab !== 'approvals') {
      setActiveTab('approvals');
    }
  }, [activeTab, canManageProject]);

  const pendingCount = useMemo(
    () => requests.filter((request) => request.status === 'pending').length,
    [requests],
  );

  const tabs = useMemo(() => {
    const base: Array<{ id: GovernanceTab; label: string; icon: typeof Shield; count?: number }> = [
      { id: 'approvals', label: 'Approvals', icon: ClipboardList, count: pendingCount || undefined },
    ];
    if (canManageProject) {
      base.push({ id: 'roles', label: 'Roles', icon: UserCheck });
    }
    return base;
  }, [canManageProject, pendingCount]);

  const run = async (work: () => Promise<void>, success: string) => {
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      await work();
      setMessage(success);
      await load();
    } catch (workError) {
      setError((workError as Error).message || 'Request failed.');
    } finally {
      setBusy(false);
    }
  };

  const submitRole = (event: FormEvent) => {
    event.preventDefault();
    void run(async () => {
      await createAccessRole(currentProject.id, accessToken!, {
        name: roleName,
        permissions: [
          {
            resource,
            action,
            effect,
            environment_id: roleEnvironment || null,
            path: rolePath || null,
            recursive: true,
          },
        ],
      });
      setRoleName('');
    }, 'Role created.');
  };

  const assignSubject = (role: AccessRole) => {
    const subject = assignmentDrafts[role.id] ?? '';
    if (!subject) return;
    const [subjectType, subjectId] = subject.split(':');
    const alreadyAssigned = assignments.some(
      (assignment) =>
        assignment.role_id === role.id &&
        (subjectType === 'machine'
          ? assignment.machine_identity_id === subjectId
          : assignment.user_id === subjectId),
    );
    if (alreadyAssigned) {
      setMessage(null);
      setError('They already have this role.');
      return;
    }
    void run(async () => {
      await createAccessAssignment(currentProject.id, accessToken!, {
        role_id: role.id,
        ...(subjectType === 'machine'
          ? { machine_identity_id: subjectId }
          : { user_id: subjectId }),
      });
      setAssignmentDrafts((drafts) => ({ ...drafts, [role.id]: '' }));
    }, `Role "${role.name}" assigned.`);
  };

  const submitProposal = (event: FormEvent) => {
    event.preventDefault();
    if (!proposalEnvironment) {
      setMessage(null);
      setError('Select an environment for the proposed change.');
      return;
    }
    void run(async () => {
      await createApprovalRequest(currentProject.id, accessToken!, {
        environment_id: proposalEnvironment,
        path: proposalPath,
        secret_key: proposalKey,
        operation: proposalOperation,
        ...(proposalOperation === 'delete' ? {} : { value: proposalValue }),
        comment: approvalComment || undefined,
      });
      setProposalKey('');
      setProposalValue('');
      setApprovalComment('');
    }, 'Change submitted for approval.');
  };

  const runSimulation = async () => {
    const [subjectType, subjectId] = simulationSubject.split(':');
    setBusy(true);
    setError(null);
    setSimulationResult(null);
    try {
      const result = await simulatePermission(currentProject.id, accessToken!, {
        ...(subjectType === 'machine'
          ? { machine_identity_id: subjectId }
          : { user_id: subjectId }),
        resource: simulationResource,
        action: simulationAction,
        environment_id: simulationEnvironment || null,
        path: simulationPath || null,
      });
      setSimulationResult(result);
    } catch (simulationError) {
      setError((simulationError as Error).message || 'Simulation failed.');
    } finally {
      setBusy(false);
    }
  };

  if (!accessToken) return <Navigate to="/login" replace />;
  if (isLoading) return <SectionLoader label="Loading access & approvals" />;

  const envSelectOptions = (placeholderLabel: string) => [
    { value: '', label: placeholderLabel },
    ...environments.map((environment) => ({
      value: environment.id,
      label: environment.name,
      dotClass: envDotClass(environment.name),
    })),
  ];
  const subjectSelectOptions = [
    { value: '', label: 'Select member or machine' },
    ...members.map((member) => ({ value: `user:${member.user_id}`, label: member.email })),
    ...machines.map((machine) => ({
      value: `machine:${machine.id}`,
      label: `Machine: ${machine.name}`,
    })),
  ];
  const rolePreview = `Members with this role ${effect === 'allow' ? 'can' : 'cannot'} ${
    action === '*' ? 'do anything with' : action
  } ${resource === '*' ? 'all resources' : resource} in ${
    roleEnvironment ? envName(environments, roleEnvironment) : 'all environments'
  }.`;

  return (
    <div className="governance-page animate-in">
      <div className="page-header">
        <div>
          <h1 className="page-heading">Access &amp; Approvals</h1>
          <p className="page-subtitle">
            Review protected secret changes and manage who can access what.
          </p>
        </div>
      </div>

      {error ? (
        <div className="auth-status auth-status-error" role="alert">
          <span>{error}</span>
        </div>
      ) : null}
      {message ? (
        <div className="auth-status auth-status-success" role="status">
          <span>{message}</span>
        </div>
      ) : null}

      <div className="governance-tabs" role="tablist" aria-label="Access and approvals sections">
        {tabs.map((tab) => {
          const Icon = tab.icon;
          const selected = activeTab === tab.id;
          return (
            <button
              key={tab.id}
              type="button"
              role="tab"
              aria-selected={selected}
              className={`governance-tab ${selected ? 'governance-tab-active' : ''}`}
              onClick={() => setActiveTab(tab.id)}
            >
              <Icon size={14} />
              <span>{tab.label}</span>
              {tab.count ? <span className="governance-tab-count">{tab.count}</span> : null}
            </button>
          );
        })}
      </div>

      {activeTab === 'approvals' ? (
        <div className="governance-panels">
          {!canManageProject ? (
          <section className="settings-section">
            <h3 className="settings-section-title">Submit a protected change</h3>
            <div className="card settings-card">
              <p className="settings-note">
                Propose a create, update, or delete that must pass an approval policy before it is
                applied.
              </p>
              <form className="governance-form-stack" onSubmit={submitProposal}>
                <div className="governance-form-grid">
                  <div className="form-group">
                    <label htmlFor="proposal-environment">Environment</label>
                    <Select
                      id="proposal-environment"
                      value={proposalEnvironment}
                      onChange={setProposalEnvironment}
                      options={envSelectOptions('Select environment')}
                    />
                  </div>
                  <div className="form-group">
                    <label htmlFor="proposal-key">Secret key name</label>
                    <input
                      id="proposal-key"
                      name="proposal-secret-key-name"
                      className="input mono"
                      autoComplete="off"
                      required
                      value={proposalKey}
                      onChange={(event) => setProposalKey(event.target.value)}
                      placeholder="SECRET_KEY"
                    />
                  </div>
                  <div className="form-group">
                    <label htmlFor="proposal-operation">Operation</label>
                    <Select
                      id="proposal-operation"
                      value={proposalOperation}
                      onChange={(next) => setProposalOperation(next as 'create' | 'update' | 'delete')}
                      options={[
                        { value: 'create', label: 'Create' },
                        { value: 'update', label: 'Update' },
                        { value: 'delete', label: 'Delete' },
                      ]}
                    />
                  </div>
                </div>
                {proposalOperation !== 'delete' ? (
                  <div className="form-group">
                    <label htmlFor="proposal-value">Secret value</label>
                    <input
                      id="proposal-value"
                      name="proposal-secret-value"
                      className="input mono input-secret-mask"
                      required
                      type="text"
                      autoComplete="off"
                      autoCorrect="off"
                      autoCapitalize="off"
                      spellCheck={false}
                      data-lpignore="true"
                      data-1p-ignore="true"
                      value={proposalValue}
                      onChange={(event) => setProposalValue(event.target.value)}
                      placeholder="Value to apply after approval"
                    />
                  </div>
                ) : null}
                <div className="form-group">
                  <label htmlFor="proposal-comment">Comment</label>
                  <input
                    id="proposal-comment"
                    className="input"
                    value={approvalComment}
                    onChange={(event) => setApprovalComment(event.target.value)}
                    placeholder="Optional note for reviewers"
                  />
                </div>
                <div className="governance-form-actions">
                  <button className="btn btn-primary" disabled={busy}>
                    Submit proposal
                  </button>
                </div>
              </form>
            </div>
          </section>
          ) : null}

          <section className="settings-section">
            <h3 className="settings-section-title">
              Approval inbox
              {pendingCount > 0 ? (
                <span className="badge badge-warning">{pendingCount} pending</span>
              ) : null}
            </h3>
            <div className="card settings-card">
              {requests.length === 0 ? (
                <div className="governance-empty">
                  <ClipboardList size={28} />
                  <h3>No approval requests</h3>
                  <p>Protected changes will show up here for review.</p>
                </div>
              ) : (
                <div className="governance-request-list">
                  {requests.map((request) => (
                    <div className="governance-request" key={request.id}>
                      <div className="governance-request-main">
                        <div className="governance-request-title-row">
                          <strong>
                            {request.operation.toUpperCase()} {request.secret_key}
                          </strong>
                          <span className={`badge ${approvalStatusBadge(request.status)}`}>
                            {request.status}
                          </span>
                        </div>
                        <div className="governance-request-meta">
                          <span>{envName(environments, request.environment_id)}</span>
                          <span>{request.path}</span>
                          <span>
                            Step {Math.min(request.current_step + 1, request.total_steps)}/
                            {request.total_steps}
                          </span>
                          <span>{formatRelativeTime(request.created_at)}</span>
                        </div>
                      </div>
                      <div className="governance-actions">
                        {request.status === 'pending' ? (
                          <>
                            <button
                              type="button"
                              className="btn btn-ghost btn-sm"
                              disabled={busy}
                              onClick={() =>
                                void run(async () => {
                                  await actOnApprovalRequest(
                                    currentProject.id,
                                    request.id,
                                    accessToken,
                                    { action: 'cancel' },
                                  );
                                }, 'Request cancelled.')
                              }
                            >
                              Cancel
                            </button>
                            <button
                              type="button"
                              className="btn btn-secondary btn-sm"
                              disabled={busy}
                              onClick={() =>
                                void run(async () => {
                                  await actOnApprovalRequest(
                                    currentProject.id,
                                    request.id,
                                    accessToken,
                                    { action: 'reject' },
                                  );
                                }, 'Request rejected.')
                              }
                            >
                              <XCircle size={13} />
                              Reject
                            </button>
                            <button
                              type="button"
                              className="btn btn-primary btn-sm"
                              disabled={busy}
                              onClick={() =>
                                void run(async () => {
                                  await actOnApprovalRequest(
                                    currentProject.id,
                                    request.id,
                                    accessToken,
                                    { action: 'approve' },
                                  );
                                }, 'Approval recorded.')
                              }
                            >
                              <CheckCircle2 size={13} />
                              Approve
                            </button>
                          </>
                        ) : null}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </section>
        </div>
      ) : null}

      {canManageProject && activeTab === 'roles' ? (
        <div className="governance-panels">
          <section className="settings-section">
            <h3 className="settings-section-title">Create a role</h3>
            <div className="card settings-card">
              <p className="settings-note">
                A role grants or denies one capability. After creating it, assign it to members or
                machines below.
              </p>
              <form className="governance-form-stack" onSubmit={submitRole}>
                <div className="governance-form-grid">
                  <div className="form-group">
                    <label htmlFor="role-name">Role name</label>
                    <input
                      id="role-name"
                      className="input"
                      required
                      value={roleName}
                      onChange={(event) => setRoleName(event.target.value)}
                      placeholder="Secrets reader"
                    />
                  </div>
                  <div className="form-group">
                    <label htmlFor="role-effect">Effect</label>
                    <Select
                      id="role-effect"
                      value={effect}
                      onChange={(next) => setEffect(next as 'allow' | 'deny')}
                      options={[
                        { value: 'allow', label: 'Allow' },
                        { value: 'deny', label: 'Deny' },
                      ]}
                    />
                  </div>
                  <div className="form-group">
                    <label htmlFor="role-action">Action</label>
                    <Select
                      id="role-action"
                      value={action}
                      onChange={setAction}
                      options={[
                        { value: 'list', label: 'List' },
                        { value: 'read', label: 'Read / reveal' },
                        { value: 'write', label: 'Write' },
                        { value: '*', label: 'All actions' },
                      ]}
                    />
                  </div>
                  <div className="form-group">
                    <label htmlFor="role-resource">Resource</label>
                    <Select
                      id="role-resource"
                      value={resource}
                      onChange={setResource}
                      options={[
                        { value: 'secrets', label: 'Secrets' },
                        { value: 'tags', label: 'Tags' },
                        { value: '*', label: 'All resources' },
                      ]}
                    />
                  </div>
                  <div className="form-group">
                    <label htmlFor="role-environment">Environment</label>
                    <Select
                      id="role-environment"
                      value={roleEnvironment}
                      onChange={setRoleEnvironment}
                      options={envSelectOptions('All environments')}
                    />
                  </div>
                </div>
                <p className="governance-role-preview">{rolePreview}</p>
                <div className="governance-form-actions">
                  <button className="btn btn-primary" disabled={busy}>
                    Create role
                  </button>
                </div>
              </form>
            </div>
          </section>

          <section className="settings-section">
            <h3 className="settings-section-title">Roles &amp; assignments</h3>
            <div className="card settings-card">
              {roles.length === 0 ? (
                <div className="governance-empty">
                  <Shield size={28} />
                  <h3>No roles yet</h3>
                  <p>Create a role above to grant scoped secret access.</p>
                </div>
              ) : (
                <div className="governance-list">
                  {roles.map((role) => {
                    const roleAssignments = assignments.filter(
                      (assignment) => assignment.role_id === role.id,
                    );
                    const draft = assignmentDrafts[role.id] ?? '';
                    return (
                      <div className="governance-role-card" key={role.id}>
                        <div>
                          <div className="governance-row-title">
                            <strong>{role.name}</strong>
                            {role.is_builtin ? (
                              <span className="badge badge-neutral">built-in</span>
                            ) : null}
                          </div>
                          <div className="text-muted">
                            {role.permissions
                              .map((permission) => permissionSummary(environments, permission))
                              .join(' · ')}
                          </div>
                        </div>
                        <div className="governance-role-members">
                          {roleAssignments.length === 0 ? (
                            <span className="text-muted">No one has this role yet.</span>
                          ) : (
                            roleAssignments.map((assignment) => {
                              const label = subjectLabel(members, machines, assignment);
                              return (
                                <span className="governance-chip" key={assignment.id}>
                                  {label}
                                  <button
                                    type="button"
                                    aria-label={`Remove ${label} from ${role.name}`}
                                    disabled={busy}
                                    onClick={() =>
                                      void run(async () => {
                                        await deleteAccessAssignment(
                                          currentProject.id,
                                          assignment.id,
                                          accessToken,
                                        );
                                      }, 'Assignment removed.')
                                    }
                                  >
                                    <X size={11} />
                                  </button>
                                </span>
                              );
                            })
                          )}
                        </div>
                        <div className="governance-role-assign">
                          <Select
                            ariaLabel={`Assign ${role.name} to`}
                            value={draft}
                            onChange={(next) =>
                              setAssignmentDrafts((drafts) => ({ ...drafts, [role.id]: next }))
                            }
                            options={subjectSelectOptions}
                          />
                          <button
                            type="button"
                            className="btn btn-secondary btn-sm"
                            disabled={busy || !draft}
                            onClick={() => assignSubject(role)}
                          >
                            Assign
                          </button>
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          </section>

          <section className="settings-section">
            <h3 className="settings-section-title">Check access</h3>
            <div className="card settings-card">
              <p className="settings-note">
                Not sure what someone can do? Pick a member or machine and check whether an action
                would be allowed.
              </p>
              <div className="governance-form-grid">
                <div className="form-group">
                  <label htmlFor="simulation-subject">Who</label>
                  <Select
                    id="simulation-subject"
                    value={simulationSubject}
                    onChange={setSimulationSubject}
                    options={subjectSelectOptions}
                  />
                </div>
                <div className="form-group">
                  <label htmlFor="simulation-action">Action</label>
                  <Select
                    id="simulation-action"
                    value={simulationAction}
                    onChange={setSimulationAction}
                    options={[
                      { value: 'list', label: 'List' },
                      { value: 'read', label: 'Read' },
                      { value: 'write', label: 'Write' },
                    ]}
                  />
                </div>
                <div className="form-group">
                  <label htmlFor="simulation-resource">Resource</label>
                  <Select
                    id="simulation-resource"
                    value={simulationResource}
                    onChange={setSimulationResource}
                    options={[
                      { value: 'secrets', label: 'Secrets' },
                      { value: 'tags', label: 'Tags' },
                    ]}
                  />
                </div>
                <div className="form-group">
                  <label htmlFor="simulation-environment">Environment</label>
                  <Select
                    id="simulation-environment"
                    value={simulationEnvironment}
                    onChange={setSimulationEnvironment}
                    options={envSelectOptions('All environments')}
                  />
                </div>
              </div>
              <div className="governance-form-actions">
                <button
                  type="button"
                  className="btn btn-secondary"
                  disabled={busy || !simulationSubject}
                  onClick={() => void runSimulation()}
                >
                  <KeyRound size={14} />
                  Check access
                </button>
              </div>
              {simulationResult ? (
                <div
                  className={`auth-status ${
                    simulationResult.allowed ? 'auth-status-success' : 'auth-status-error'
                  }`}
                  role="status"
                >
                  <span>
                    {simulationResult.allowed ? 'Allowed' : 'Denied'} —{' '}
                    {SIMULATION_REASONS[simulationResult.reason] ?? simulationResult.reason}
                  </span>
                </div>
              ) : null}
            </div>
          </section>
        </div>
      ) : null}
    </div>
  );
}
