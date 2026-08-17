import { FormEvent, useCallback, useEffect, useMemo, useState } from 'react';
import { Navigate, useOutletContext } from 'react-router-dom';
import {
  CheckCircle2,
  ClipboardList,
  History,
  KeyRound,
  RotateCcw,
  Shield,
  ShieldCheck,
  UserCheck,
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
  createApprovalPolicy,
  deleteAccessAssignment,
  getSecretRetention,
  listAccessAssignments,
  listAccessRoles,
  listApprovalPolicies,
  listApprovalRequests,
  listMachineIdentities,
  listMembers,
  recoverEnvironmentSecrets,
  updateSecretRetention,
  simulatePermission,
} from '../lib/api';
import { formatRelativeTime } from '../lib/format';
import type {
  AccessRole,
  AccessRoleAssignment,
  ApprovalPolicy,
  ApprovalRequest,
  Environment,
  MachineIdentity,
  Member,
  PermissionSimulation,
  Project,
  RecoveryResult,
  SecretRetention,
} from '../types/api';

interface OutletContextType {
  currentProject: Project;
  environments: Environment[];
  canManageProject: boolean;
}

type GovernanceTab = 'approvals' | 'roles' | 'policies' | 'retention';

const inputNumber = (value: string): number | null => (value.trim() ? Number(value) : null);

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
  const [policies, setPolicies] = useState<ApprovalPolicy[]>([]);
  const [requests, setRequests] = useState<ApprovalRequest[]>([]);
  const [members, setMembers] = useState<Member[]>([]);
  const [machines, setMachines] = useState<MachineIdentity[]>([]);
  const [retention, setRetention] = useState<SecretRetention | null>(null);
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
  const [assignmentRole, setAssignmentRole] = useState('');
  const [assignmentSubject, setAssignmentSubject] = useState('');

  const [policyName, setPolicyName] = useState('Production changes');
  const [policyEnvironment, setPolicyEnvironment] = useState('');
  const policyPath = '/';
  const [approver, setApprover] = useState('');
  const [secondApprover, setSecondApprover] = useState('');
  const [approvalComment, setApprovalComment] = useState('');

  const [recoveryEnvironment, setRecoveryEnvironment] = useState('');
  const [recoveryAt, setRecoveryAt] = useState('');
  const [recoveryPath, setRecoveryPath] = useState('/');
  const [recoveryResult, setRecoveryResult] = useState<RecoveryResult | null>(null);
  const [simulationSubject, setSimulationSubject] = useState('');
  const [simulationResource, setSimulationResource] = useState('secrets');
  const [simulationAction, setSimulationAction] = useState('read');
  const simulationPath = '/';
  const [simulationEnvironment, setSimulationEnvironment] = useState('');
  const [simulationResult, setSimulationResult] = useState<PermissionSimulation | null>(null);
  const [proposalEnvironment, setProposalEnvironment] = useState('');
  const proposalPath = '/';
  const [proposalKey, setProposalKey] = useState('');
  const [proposalOperation, setProposalOperation] = useState<'create' | 'update' | 'delete'>(
    'create',
  );
  const [proposalValue, setProposalValue] = useState('');

  const load = useCallback(async () => {
    if (!accessToken) return;
    setIsLoading(true);
    setError(null);
    try {
      const common = listApprovalRequests(currentProject.id, accessToken);
      if (canManageProject) {
        const [
          nextRoles,
          nextAssignments,
          nextPolicies,
          nextRequests,
          nextMembers,
          nextMachines,
          nextRetention,
        ] = await Promise.all([
          listAccessRoles(currentProject.id, accessToken),
          listAccessAssignments(currentProject.id, accessToken),
          listApprovalPolicies(currentProject.id, accessToken),
          common,
          listMembers(currentProject.id, accessToken),
          listMachineIdentities(currentProject.id, accessToken),
          getSecretRetention(currentProject.id, accessToken),
        ]);
        setRoles(nextRoles);
        setAssignments(nextAssignments);
        setPolicies(nextPolicies);
        setRequests(nextRequests);
        setMembers(nextMembers);
        setMachines(nextMachines);
        setRetention(nextRetention);
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
      base.push(
        { id: 'roles', label: 'Roles', icon: UserCheck },
        { id: 'policies', label: 'Policies', icon: ShieldCheck },
        { id: 'retention', label: 'Retention', icon: History },
      );
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
    }, 'Custom role created.');
  };

  const submitAssignment = (event: FormEvent) => {
    event.preventDefault();
    if (!assignmentRole || !assignmentSubject) {
      setError('Select both a role and a member to assign.');
      return;
    }
    const [subjectType, subjectId] = assignmentSubject.split(':');
    void run(async () => {
      await createAccessAssignment(currentProject.id, accessToken!, {
        role_id: assignmentRole,
        ...(subjectType === 'machine'
          ? { machine_identity_id: subjectId }
          : { user_id: subjectId }),
      });
      setAssignmentRole('');
      setAssignmentSubject('');
    }, 'Role assigned.');
  };

  const submitPolicy = (event: FormEvent) => {
    event.preventDefault();
    if (!approver) {
      setError('Select a first approver for the policy.');
      return;
    }
    const [approverType, approverId] = approver.split(':');
    const [secondType, secondId] = secondApprover.split(':');
    void run(async () => {
      await createApprovalPolicy(currentProject.id, accessToken!, {
        name: policyName,
        environment_id: policyEnvironment || null,
        path: policyPath,
        recursive: true,
        actions: ['create', 'update', 'delete'],
        steps: [
          {
            name: 'Approval',
            min_approvals: 1,
            approver_user_ids: approverType === 'user' ? [approverId] : [],
            approver_role_ids: approverType === 'role' ? [approverId] : [],
          },
          ...(secondApprover
            ? [
                {
                  name: 'Final approval',
                  min_approvals: 1,
                  approver_user_ids: secondType === 'user' ? [secondId] : [],
                  approver_role_ids: secondType === 'role' ? [secondId] : [],
                },
              ]
            : []),
        ],
        prevent_self_approval: true,
        enabled: true,
      });
      setApprover('');
      setSecondApprover('');
    }, 'Approval policy created.');
  };

  const saveRetention = () => {
    if (!retention) return;
    void run(async () => {
      await updateSecretRetention(currentProject.id, accessToken!, {
        retain_versions: retention.retain_versions,
        retain_days: retention.retain_days,
        archive_deleted_after_days: retention.archive_deleted_after_days,
      });
    }, 'Retention policy saved.');
  };

  const recover = (apply: boolean) => {
    if (!recoveryEnvironment || !recoveryAt) return;
    void run(async () => {
      const result = await recoverEnvironmentSecrets(
        currentProject.id,
        recoveryEnvironment,
        accessToken!,
        {
          at: new Date(recoveryAt).toISOString(),
          path: recoveryPath,
          recursive: true,
          dry_run: !apply,
        },
      );
      setRecoveryResult(result);
    }, apply ? 'Recovery applied.' : 'Recovery preview complete.');
  };

  const submitProposal = (event: FormEvent) => {
    event.preventDefault();
    if (!proposalEnvironment) {
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
    }, 'Change submitted for approval.');
  };

  const runSimulation = () => {
    const [subjectType, subjectId] = simulationSubject.split(':');
    void run(async () => {
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
    }, 'Permission simulation complete.');
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
    { value: '', label: 'Select member' },
    ...members.map((member) => ({ value: `user:${member.user_id}`, label: member.email })),
  ];
  const approverSelectOptions = (placeholderLabel: string) => [
    { value: '', label: placeholderLabel },
    ...members.map((member) => ({ value: `user:${member.user_id}`, label: member.email })),
    ...roles.map((role) => ({ value: `role:${role.id}`, label: `Role: ${role.name}` })),
  ];

  return (
    <div className="governance-page animate-in">
      <div className="page-header">
        <div>
          <h1 className="page-heading">Access & Approvals</h1>
          <p className="page-subtitle">
            Review protected secret changes, manage scoped roles, and recover historical values.
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
                        <button
                          type="button"
                          className="btn btn-ghost btn-sm"
                          disabled={busy}
                          onClick={() =>
                            void run(async () => {
                              await actOnApprovalRequest(currentProject.id, request.id, accessToken, {
                                action: 'comment',
                                comment: approvalComment || 'Reviewed',
                              });
                            }, 'Comment added.')
                          }
                        >
                          Comment
                        </button>
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
                                    { action: 'cancel', comment: approvalComment || undefined },
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
                                    { action: 'reject', comment: approvalComment || undefined },
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
                                    { action: 'approve', comment: approvalComment || undefined },
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
                    <label htmlFor="role-environment">Environment</label>
                    <Select
                      id="role-environment"
                      value={roleEnvironment}
                      onChange={setRoleEnvironment}
                      options={envSelectOptions('All environments')}
                    />
                  </div>
                </div>
                <div className="governance-form-actions">
                  <button className="btn btn-primary" disabled={busy}>
                    Create role
                  </button>
                </div>
              </form>
            </div>
          </section>

          <section className="settings-section">
            <h3 className="settings-section-title">Roles</h3>
            <div className="card settings-card">
              {roles.length === 0 ? (
                <div className="governance-empty">
                  <Shield size={28} />
                  <h3>No roles yet</h3>
                  <p>Create a custom role to grant scoped secret access.</p>
                </div>
              ) : (
                <div className="governance-list">
                  {roles.map((role) => (
                    <div className="governance-row" key={role.id}>
                      <div>
                        <div className="governance-row-title">
                          <strong>{role.name}</strong>
                          {role.is_builtin ? <span className="badge badge-neutral">built-in</span> : null}
                          {role.organization_id ? (
                            <span className="badge badge-info">organization</span>
                          ) : (
                            <span className="badge badge-neutral">project</span>
                          )}
                        </div>
                        <div className="text-muted">
                          {role.permissions
                            .map(
                              (permission) =>
                                `${permission.effect} ${permission.resource}:${permission.action}${
                                  permission.path ? ` at ${permission.path}` : ''
                                }`,
                            )
                            .join(' · ')}
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </section>

          <section className="settings-section">
            <h3 className="settings-section-title">Assignments</h3>
            <div className="card settings-card">
              <form className="governance-form-stack" onSubmit={submitAssignment}>
                <div className="governance-form-grid">
                  <div className="form-group">
                    <label htmlFor="assignment-role">Role</label>
                    <Select
                      id="assignment-role"
                      value={assignmentRole}
                      onChange={setAssignmentRole}
                      options={[
                        { value: '', label: 'Select role' },
                        ...roles.map((role) => ({ value: role.id, label: role.name })),
                      ]}
                    />
                  </div>
                  <div className="form-group">
                    <label htmlFor="assignment-subject">Member</label>
                    <Select
                      id="assignment-subject"
                      value={assignmentSubject}
                      onChange={setAssignmentSubject}
                      options={subjectSelectOptions}
                    />
                  </div>
                </div>
                <div className="governance-form-actions">
                  <button className="btn btn-secondary" disabled={busy}>
                    Assign role
                  </button>
                </div>
              </form>

              {assignments.length === 0 ? (
                <p className="text-muted governance-list-empty">No role assignments yet.</p>
              ) : (
                <div className="governance-list">
                  {assignments.map((assignment) => (
                    <div className="governance-row" key={assignment.id}>
                      <div>
                        <strong>
                          {roles.find((role) => role.id === assignment.role_id)?.name ?? 'Role'}
                        </strong>
                        <div className="text-muted">
                          {subjectLabel(members, machines, assignment)}
                        </div>
                      </div>
                      <button
                        type="button"
                        className="btn btn-ghost btn-sm"
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
                        Remove
                      </button>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </section>

          <section className="settings-section">
            <h3 className="settings-section-title">Permission simulator</h3>
            <div className="card settings-card">
              <p className="settings-note">
                Check whether a member or machine identity is allowed to perform an action.
              </p>
              <div className="governance-form-grid">
                <div className="form-group">
                  <label htmlFor="simulation-subject">Subject</label>
                  <Select
                    id="simulation-subject"
                    value={simulationSubject}
                    onChange={setSimulationSubject}
                    options={subjectSelectOptions}
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
                  onClick={runSimulation}
                >
                  <KeyRound size={14} />
                  Simulate access
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
                    {simulationResult.allowed ? 'Allowed' : 'Denied'}: {simulationResult.reason}
                  </span>
                </div>
              ) : null}
            </div>
          </section>
        </div>
      ) : null}

      {canManageProject && activeTab === 'policies' ? (
        <div className="governance-panels">
          <section className="settings-section">
            <h3 className="settings-section-title">Create approval policy</h3>
            <div className="card settings-card">
              <p className="settings-note">
                Require one or two approval steps before create, update, or delete operations can be
                applied.
              </p>
              <form className="governance-form-stack" onSubmit={submitPolicy}>
                <div className="governance-form-grid">
                  <div className="form-group">
                    <label htmlFor="policy-name">Policy name</label>
                    <input
                      id="policy-name"
                      className="input"
                      required
                      value={policyName}
                      onChange={(event) => setPolicyName(event.target.value)}
                      placeholder="Production changes"
                    />
                  </div>
                  <div className="form-group">
                    <label htmlFor="policy-environment">Environment</label>
                    <Select
                      id="policy-environment"
                      value={policyEnvironment}
                      onChange={setPolicyEnvironment}
                      options={envSelectOptions('All environments')}
                    />
                  </div>
                  <div className="form-group">
                    <label htmlFor="policy-approver">First approver</label>
                    <Select
                      id="policy-approver"
                      value={approver}
                      onChange={setApprover}
                      options={approverSelectOptions('Select approver')}
                    />
                  </div>
                  <div className="form-group">
                    <label htmlFor="policy-second-approver">Second approver</label>
                    <Select
                      id="policy-second-approver"
                      value={secondApprover}
                      onChange={setSecondApprover}
                      options={approverSelectOptions('No second step')}
                    />
                  </div>
                </div>
                <div className="governance-form-actions">
                  <button className="btn btn-primary" disabled={busy}>
                    Protect changes
                  </button>
                </div>
              </form>
            </div>
          </section>

          <section className="settings-section">
            <h3 className="settings-section-title">Active policies</h3>
            <div className="card settings-card">
              {policies.length === 0 ? (
                <div className="governance-empty">
                  <ShieldCheck size={28} />
                  <h3>No approval policies</h3>
                  <p>Protect production paths so secret changes need review first.</p>
                </div>
              ) : (
                <div className="governance-list">
                  {policies.map((policy) => (
                    <div className="governance-row" key={policy.id}>
                      <div>
                        <div className="governance-row-title">
                          <strong>{policy.name}</strong>
                          <span
                            className={`badge ${policy.enabled ? 'badge-success' : 'badge-neutral'}`}
                          >
                            {policy.enabled ? 'enabled' : 'disabled'}
                          </span>
                        </div>
                        <div className="text-muted">
                          {envName(environments, policy.environment_id)} · {policy.path} ·{' '}
                          {policy.steps.length} step{policy.steps.length === 1 ? '' : 's'} ·{' '}
                          {policy.actions.join(', ')}
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </section>
        </div>
      ) : null}

      {canManageProject && activeTab === 'retention' && retention ? (
        <div className="governance-panels">
          <section className="settings-section">
            <h3 className="settings-section-title">Retention policy</h3>
            <div className="card settings-card">
              <p className="settings-note">
                Control how long secret versions are kept before cleanup.
              </p>
              <div className="governance-form-grid">
                <div className="form-group">
                  <label htmlFor="retain-versions">Versions to keep</label>
                  <input
                    id="retain-versions"
                    className="input"
                    type="number"
                    min="1"
                    value={retention.retain_versions}
                    onChange={(event) =>
                      setRetention({ ...retention, retain_versions: Number(event.target.value) })
                    }
                  />
                </div>
                <div className="form-group">
                  <label htmlFor="retain-days">Retain for days</label>
                  <input
                    id="retain-days"
                    className="input"
                    type="number"
                    value={retention.retain_days ?? ''}
                    onChange={(event) =>
                      setRetention({
                        ...retention,
                        retain_days: inputNumber(event.target.value),
                      })
                    }
                    placeholder="Optional"
                  />
                </div>
                <div className="form-group">
                  <label htmlFor="archive-deleted">Archive deleted after days</label>
                  <input
                    id="archive-deleted"
                    className="input"
                    type="number"
                    value={retention.archive_deleted_after_days ?? ''}
                    onChange={(event) =>
                      setRetention({
                        ...retention,
                        archive_deleted_after_days: inputNumber(event.target.value),
                      })
                    }
                    placeholder="Optional"
                  />
                </div>
              </div>
              <div className="governance-form-actions">
                <button
                  type="button"
                  className="btn btn-secondary"
                  disabled={busy}
                  onClick={saveRetention}
                >
                  Save retention
                </button>
              </div>
            </div>
          </section>

          <section className="settings-section">
            <h3 className="settings-section-title">Point-in-time recovery</h3>
            <div className="card settings-card">
              <p className="settings-note">
                Preview or restore secrets for an environment as they existed at a chosen time.
              </p>
              <div className="governance-form-grid">
                <div className="form-group">
                  <label htmlFor="recovery-environment">Environment</label>
                  <Select
                    id="recovery-environment"
                    value={recoveryEnvironment}
                    onChange={setRecoveryEnvironment}
                    options={envSelectOptions('Select environment')}
                  />
                </div>
                <div className="form-group">
                  <label htmlFor="recovery-at">Restore point</label>
                  <input
                    id="recovery-at"
                    className="input"
                    type="datetime-local"
                    value={recoveryAt}
                    onChange={(event) => setRecoveryAt(event.target.value)}
                  />
                </div>
                <div className="form-group">
                  <label htmlFor="recovery-path">Path</label>
                  <input
                    id="recovery-path"
                    className="input"
                    value={recoveryPath}
                    onChange={(event) => setRecoveryPath(event.target.value)}
                    placeholder="/"
                  />
                </div>
              </div>
              <div className="governance-form-actions">
                <button
                  type="button"
                  className="btn btn-secondary"
                  disabled={busy || !recoveryAt || !recoveryEnvironment}
                  onClick={() => recover(false)}
                >
                  <RotateCcw size={14} />
                  Preview
                </button>
                <button
                  type="button"
                  className="btn btn-danger"
                  disabled={busy || !recoveryResult || recoveryResult.dry_run === false}
                  onClick={() => recover(true)}
                >
                  Apply recovery
                </button>
              </div>
              {recoveryResult ? (
                <div className="governance-recovery-result">
                  <strong>
                    {recoveryResult.changed} change{recoveryResult.changed === 1 ? '' : 's'}
                    {recoveryResult.dry_run ? ' (preview)' : ' applied'}
                  </strong>
                  <p className="text-muted">
                    {recoveryResult.items.length
                      ? recoveryResult.items
                          .map((item) => `${item.action} ${item.path}/${item.key}`)
                          .join(', ')
                      : 'No secrets would change.'}
                  </p>
                </div>
              ) : null}
            </div>
          </section>
        </div>
      ) : null}
    </div>
  );
}
