import { FormEvent, useCallback, useEffect, useState } from 'react';
import { Navigate, useOutletContext } from 'react-router-dom';
import { useAuth } from '../auth/useAuth';
import SectionLoader from '../components/SectionLoader';
import {
  actOnApprovalRequest,
  createAccessAssignment,
  createAccessRole,
  createApprovalRequest,
  createApprovalPolicy,
  createOrganization,
  deleteAccessAssignment,
  getSecretRetention,
  listAccessAssignments,
  listAccessRoles,
  listApprovalPolicies,
  listApprovalRequests,
  listMachineIdentities,
  listMembers,
  listOrganizations,
  recoverEnvironmentSecrets,
  updateSecretRetention,
  updateProject,
  simulatePermission,
} from '../lib/api';
import type {
  AccessRole,
  AccessRoleAssignment,
  ApprovalPolicy,
  ApprovalRequest,
  Environment,
  MachineIdentity,
  Member,
  Organization,
  PermissionSimulation,
  Project,
  RecoveryResult,
  SecretRetention,
} from '../types/api';

interface OutletContextType {
  currentProject: Project;
  environments: Environment[];
  canManageProject: boolean;
  onProjectUpdated: (project: Project) => void;
}

const inputNumber = (value: string): number | null => (value.trim() ? Number(value) : null);

export default function GovernancePage() {
  const { currentProject, environments, canManageProject, onProjectUpdated } = useOutletContext<OutletContextType>();
  const { accessToken } = useAuth();
  const [roles, setRoles] = useState<AccessRole[]>([]);
  const [assignments, setAssignments] = useState<AccessRoleAssignment[]>([]);
  const [policies, setPolicies] = useState<ApprovalPolicy[]>([]);
  const [requests, setRequests] = useState<ApprovalRequest[]>([]);
  const [members, setMembers] = useState<Member[]>([]);
  const [machines, setMachines] = useState<MachineIdentity[]>([]);
  const [retention, setRetention] = useState<SecretRetention | null>(null);
  const [organizations, setOrganizations] = useState<Organization[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const [roleName, setRoleName] = useState('');
  const [resource, setResource] = useState('secrets');
  const [action, setAction] = useState('read');
  const [effect, setEffect] = useState<'allow' | 'deny'>('allow');
  const [roleEnvironment, setRoleEnvironment] = useState('');
  const [rolePath, setRolePath] = useState('/');
  const [roleScope, setRoleScope] = useState<'project' | 'organization'>('project');
  const [assignmentRole, setAssignmentRole] = useState('');
  const [assignmentSubject, setAssignmentSubject] = useState('');

  const [policyName, setPolicyName] = useState('Production changes');
  const [policyEnvironment, setPolicyEnvironment] = useState('');
  const [policyPath, setPolicyPath] = useState('/');
  const [approver, setApprover] = useState('');
  const [secondApprover, setSecondApprover] = useState('');
  const [approvalComment, setApprovalComment] = useState('');

  const [recoveryEnvironment, setRecoveryEnvironment] = useState('');
  const [recoveryAt, setRecoveryAt] = useState('');
  const [recoveryPath, setRecoveryPath] = useState('/');
  const [recoveryResult, setRecoveryResult] = useState<RecoveryResult | null>(null);
  const [organizationName, setOrganizationName] = useState('');
  const [selectedOrganization, setSelectedOrganization] = useState(currentProject.organization_id ?? '');
  const [simulationSubject, setSimulationSubject] = useState('');
  const [simulationResource, setSimulationResource] = useState('secrets');
  const [simulationAction, setSimulationAction] = useState('read');
  const [simulationPath, setSimulationPath] = useState('/');
  const [simulationEnvironment, setSimulationEnvironment] = useState('');
  const [simulationResult, setSimulationResult] = useState<PermissionSimulation | null>(null);
  const [proposalEnvironment, setProposalEnvironment] = useState('');
  const [proposalPath, setProposalPath] = useState('/');
  const [proposalKey, setProposalKey] = useState('');
  const [proposalOperation, setProposalOperation] = useState<'create' | 'update' | 'delete'>('create');
  const [proposalValue, setProposalValue] = useState('');

  const load = useCallback(async () => {
    if (!accessToken) return;
    setIsLoading(true);
    setError(null);
    try {
      const common = listApprovalRequests(currentProject.id, accessToken);
      if (canManageProject) {
        const [nextRoles, nextAssignments, nextPolicies, nextRequests, nextMembers, nextMachines, nextRetention, nextOrganizations] = await Promise.all([
          listAccessRoles(currentProject.id, accessToken),
          listAccessAssignments(currentProject.id, accessToken),
          listApprovalPolicies(currentProject.id, accessToken),
          common,
          listMembers(currentProject.id, accessToken),
          listMachineIdentities(currentProject.id, accessToken),
          getSecretRetention(currentProject.id, accessToken),
          listOrganizations(accessToken),
        ]);
        setRoles(nextRoles);
        setAssignments(nextAssignments);
        setPolicies(nextPolicies);
        setRequests(nextRequests);
        setMembers(nextMembers);
        setMachines(nextMachines);
        setRetention(nextRetention);
        setOrganizations(nextOrganizations);
      } else {
        setRequests(await common);
      }
    } catch (loadError) {
      setError((loadError as Error).message || 'Failed to load governance settings.');
    } finally {
      setIsLoading(false);
    }
  }, [accessToken, canManageProject, currentProject.id]);

  useEffect(() => { void load(); }, [load]);
  useEffect(() => { setSelectedOrganization(currentProject.organization_id ?? ''); }, [currentProject.organization_id]);

  const run = async (work: () => Promise<void>, success: string) => {
    setBusy(true); setError(null); setMessage(null);
    try { await work(); setMessage(success); await load(); }
    catch (workError) { setError((workError as Error).message || 'Request failed.'); }
    finally { setBusy(false); }
  };

  const submitRole = (event: FormEvent) => {
    event.preventDefault();
    void run(async () => {
      await createAccessRole(currentProject.id, accessToken!, {
        name: roleName,
        ...(roleScope === 'organization' && currentProject.organization_id ? { organization_id: currentProject.organization_id } : {}),
        permissions: [{ resource, action, effect, environment_id: roleEnvironment || null, path: rolePath || null, recursive: true }],
      });
      setRoleName('');
    }, 'Custom role created.');
  };

  const submitAssignment = (event: FormEvent) => {
    event.preventDefault();
    const [subjectType, subjectId] = assignmentSubject.split(':');
    void run(async () => {
      await createAccessAssignment(currentProject.id, accessToken!, {
        role_id: assignmentRole,
        ...(subjectType === 'machine' ? { machine_identity_id: subjectId } : { user_id: subjectId }),
      });
    }, 'Role assigned.');
  };

  const submitPolicy = (event: FormEvent) => {
    event.preventDefault();
    const [approverType, approverId] = approver.split(':');
    const [secondType, secondId] = secondApprover.split(':');
    void run(async () => {
      await createApprovalPolicy(currentProject.id, accessToken!, {
        name: policyName,
        environment_id: policyEnvironment || null,
        path: policyPath,
        recursive: true,
        actions: ['create', 'update', 'delete'],
        steps: [{
          name: 'Approval', min_approvals: 1,
          approver_user_ids: approverType === 'user' ? [approverId] : [],
          approver_role_ids: approverType === 'role' ? [approverId] : [],
        }, ...(secondApprover ? [{
          name: 'Final approval', min_approvals: 1,
          approver_user_ids: secondType === 'user' ? [secondId] : [],
          approver_role_ids: secondType === 'role' ? [secondId] : [],
        }] : [])],
        prevent_self_approval: true,
        enabled: true,
      });
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
      const result = await recoverEnvironmentSecrets(currentProject.id, recoveryEnvironment, accessToken!, {
        at: new Date(recoveryAt).toISOString(), path: recoveryPath, recursive: true, dry_run: !apply,
      });
      setRecoveryResult(result);
    }, apply ? 'Recovery applied.' : 'Recovery preview complete.');
  };

  const submitProposal = (event: FormEvent) => {
    event.preventDefault();
    void run(async () => {
      await createApprovalRequest(currentProject.id, accessToken!, {
        environment_id: proposalEnvironment,
        path: proposalPath,
        secret_key: proposalKey,
        operation: proposalOperation,
        ...(proposalOperation === 'delete' ? {} : { value: proposalValue }),
        comment: approvalComment || undefined,
      });
      setProposalKey(''); setProposalValue('');
    }, 'Change submitted for approval.');
  };

  const runSimulation = () => {
    const [subjectType, subjectId] = simulationSubject.split(':');
    void run(async () => {
      const result = await simulatePermission(currentProject.id, accessToken!, {
        ...(subjectType === 'machine' ? { machine_identity_id: subjectId } : { user_id: subjectId }),
        resource: simulationResource,
        action: simulationAction,
        environment_id: simulationEnvironment || null,
        path: simulationPath || null,
      });
      setSimulationResult(result);
    }, 'Permission simulation complete.');
  };

  const saveOrganization = () => {
    void run(async () => {
      const updated = await updateProject(currentProject.id, accessToken!, { organization_id: selectedOrganization || null });
      onProjectUpdated(updated);
    }, 'Project organization updated.');
  };

  if (!accessToken) return <Navigate to="/login" replace />;
  if (isLoading) return <SectionLoader label="Loading governance" />;

  return (
    <div className="settings-page animate-in">
      <div className="page-header"><div><h1 className="page-heading">Access & approvals</h1><p className="page-subtitle">Scoped roles, protected changes, retention and recovery.</p></div></div>
      {error && <div className="alert alert-error">{error}</div>}
      {message && <div className="alert alert-success">{message}</div>}

      <div className="settings-section">
        <h3 className="settings-section-title">Submit a protected change</h3>
        <div className="card settings-card">
          <form className="governance-form" onSubmit={submitProposal}>
            <select className="input" required value={proposalEnvironment} onChange={(event) => setProposalEnvironment(event.target.value)}><option value="">Environment</option>{environments.map((environment) => <option key={environment.id} value={environment.id}>{environment.name}</option>)}</select>
            <input className="input" required value={proposalPath} onChange={(event) => setProposalPath(event.target.value)} placeholder="/path" />
            <input className="input" required value={proposalKey} onChange={(event) => setProposalKey(event.target.value)} placeholder="SECRET_KEY" />
            <select className="input" value={proposalOperation} onChange={(event) => setProposalOperation(event.target.value as 'create' | 'update' | 'delete')}><option value="create">Create</option><option value="update">Update</option><option value="delete">Delete</option></select>
            {proposalOperation !== 'delete' && <input className="input" required type="password" autoComplete="off" value={proposalValue} onChange={(event) => setProposalValue(event.target.value)} placeholder="Secret value" />}
            <button className="btn btn-primary" disabled={busy}>Submit proposal</button>
          </form>
        </div>
      </div>

      <div className="settings-section">
        <h3 className="settings-section-title">Approval inbox</h3>
        <div className="card settings-card">
          {requests.length === 0 ? <p className="text-muted">No approval requests.</p> : requests.map((request) => (
            <div className="governance-row" key={request.id}>
              <div><strong>{request.operation.toUpperCase()} {request.secret_key}</strong><div className="text-muted">{request.path} · {request.status} · step {Math.min(request.current_step + 1, request.total_steps)}/{request.total_steps}</div></div>
              <div className="governance-actions">
                <button className="btn btn-secondary btn-sm" disabled={busy} onClick={() => void run(async () => { await actOnApprovalRequest(currentProject.id, request.id, accessToken, { action: 'comment', comment: approvalComment || 'Reviewed' }); }, 'Comment added.')}>Comment</button>
                {request.status === 'pending' && <><button className="btn btn-ghost btn-sm" disabled={busy} onClick={() => void run(async () => { await actOnApprovalRequest(currentProject.id, request.id, accessToken, { action: 'cancel', comment: approvalComment || undefined }); }, 'Request cancelled.')}>Cancel</button><button className="btn btn-secondary btn-sm" disabled={busy} onClick={() => void run(async () => { await actOnApprovalRequest(currentProject.id, request.id, accessToken, { action: 'reject', comment: approvalComment || undefined }); }, 'Request rejected.')}>Reject</button><button className="btn btn-primary btn-sm" disabled={busy} onClick={() => void run(async () => { await actOnApprovalRequest(currentProject.id, request.id, accessToken, { action: 'approve', comment: approvalComment || undefined }); }, 'Approval recorded.')}>Approve</button></>}
              </div>
            </div>
          ))}
          <input className="input" value={approvalComment} onChange={(event) => setApprovalComment(event.target.value)} placeholder="Optional action comment" />
        </div>
      </div>

      {canManageProject && <>
        <div className="settings-section"><h3 className="settings-section-title">Organization scope</h3><div className="card settings-card">
          <div className="governance-form"><input className="input" value={organizationName} onChange={(event) => setOrganizationName(event.target.value)} placeholder="New organization name" /><button className="btn btn-secondary" disabled={busy || !organizationName.trim()} onClick={() => void run(async () => { const organization = await createOrganization(accessToken, { name: organizationName }); setOrganizations((items) => [...items, organization]); setSelectedOrganization(organization.id); setOrganizationName(''); }, 'Organization created. Attach it to enable organization roles.')}>Create organization</button><select className="input" value={selectedOrganization} onChange={(event) => setSelectedOrganization(event.target.value)}><option value="">No organization</option>{organizations.map((organization) => <option key={organization.id} value={organization.id}>{organization.name}</option>)}</select><button className="btn btn-primary" disabled={busy} onClick={saveOrganization}>Save scope</button></div>
          <p className="text-muted">Organization roles apply to every attached project. Only the organization owner can assign them.</p>
        </div></div>

        <div className="settings-section"><h3 className="settings-section-title">Roles and scoped permissions</h3><div className="card settings-card">
          <form className="governance-form" onSubmit={submitRole}>
            <input className="input" required value={roleName} onChange={(event) => setRoleName(event.target.value)} placeholder="Custom role name" />
            <select className="input" value={roleScope} onChange={(event) => setRoleScope(event.target.value as 'project' | 'organization')}><option value="project">Project role</option>{currentProject.organization_id && <option value="organization">Organization role</option>}</select>
            <select className="input" value={resource} onChange={(event) => setResource(event.target.value)}><option value="secrets">Secrets</option><option value="folders">Folders</option><option value="tags">Tags</option><option value="imports">Imports</option><option value="*">All resources</option></select>
            <select className="input" value={action} onChange={(event) => setAction(event.target.value)}><option value="list">List</option><option value="read">Read/reveal</option><option value="write">Write</option><option value="*">All actions</option></select>
            <select className="input" value={effect} onChange={(event) => setEffect(event.target.value as 'allow' | 'deny')}><option value="allow">Allow</option><option value="deny">Deny</option></select>
            <select className="input" value={roleEnvironment} onChange={(event) => setRoleEnvironment(event.target.value)}><option value="">All environments</option>{environments.map((environment) => <option key={environment.id} value={environment.id}>{environment.name}</option>)}</select>
            <input className="input" value={rolePath} onChange={(event) => setRolePath(event.target.value)} placeholder="/path" />
            <button className="btn btn-primary" disabled={busy}>Create role</button>
          </form>
          <div className="governance-list">{roles.map((role) => <div className="governance-row" key={role.id}><div><strong>{role.name}</strong>{role.is_builtin && <span className="badge">built-in</span>}<div className="text-muted">{role.permissions.map((permission) => `${permission.effect} ${permission.resource}:${permission.action}${permission.path ? ` at ${permission.path}` : ''}`).join(', ')}</div></div></div>)}</div>
          <form className="governance-form" onSubmit={submitAssignment}>
            <select className="input" required value={assignmentRole} onChange={(event) => setAssignmentRole(event.target.value)}><option value="">Select role</option>{roles.map((role) => <option key={role.id} value={role.id}>{role.name}</option>)}</select>
            <select className="input" required value={assignmentSubject} onChange={(event) => setAssignmentSubject(event.target.value)}><option value="">Select user or machine</option>{members.map((member) => <option key={member.user_id} value={`user:${member.user_id}`}>{member.email}</option>)}{machines.map((machine) => <option key={machine.id} value={`machine:${machine.id}`}>Machine: {machine.name}</option>)}</select>
            <button className="btn btn-secondary" disabled={busy}>Assign role</button>
          </form>
          {assignments.map((assignment) => <div className="governance-row" key={assignment.id}><span>{roles.find((role) => role.id === assignment.role_id)?.name ?? 'Role'} → {members.find((member) => member.user_id === assignment.user_id)?.email ?? machines.find((machine) => machine.id === assignment.machine_identity_id)?.name ?? 'Subject'}</span><button className="btn btn-ghost btn-sm" disabled={busy} onClick={() => void run(async () => { await deleteAccessAssignment(currentProject.id, assignment.id, accessToken); }, 'Assignment removed.')}>Remove</button></div>)}
          <div className="governance-form">
            <select className="input" required value={simulationSubject} onChange={(event) => setSimulationSubject(event.target.value)}><option value="">Simulation subject</option>{members.map((member) => <option key={member.user_id} value={`user:${member.user_id}`}>{member.email}</option>)}{machines.map((machine) => <option key={machine.id} value={`machine:${machine.id}`}>Machine: {machine.name}</option>)}</select>
            <select className="input" value={simulationResource} onChange={(event) => setSimulationResource(event.target.value)}><option value="secrets">Secrets</option><option value="folders">Folders</option><option value="tags">Tags</option><option value="imports">Imports</option></select>
            <select className="input" value={simulationAction} onChange={(event) => setSimulationAction(event.target.value)}><option value="list">List</option><option value="read">Read</option><option value="write">Write</option></select>
            <select className="input" value={simulationEnvironment} onChange={(event) => setSimulationEnvironment(event.target.value)}><option value="">All environments</option>{environments.map((environment) => <option key={environment.id} value={environment.id}>{environment.name}</option>)}</select>
            <input className="input" value={simulationPath} onChange={(event) => setSimulationPath(event.target.value)} placeholder="/path" />
            <button type="button" className="btn btn-secondary" disabled={busy || !simulationSubject} onClick={runSimulation}>Simulate</button>
          </div>
          {simulationResult && <div className={`alert ${simulationResult.allowed ? 'alert-success' : 'alert-error'}`}>{simulationResult.allowed ? 'Allowed' : 'Denied'}: {simulationResult.reason}</div>}
        </div></div>

        <div className="settings-section"><h3 className="settings-section-title">Approval policies</h3><div className="card settings-card">
          <form className="governance-form" onSubmit={submitPolicy}>
            <input className="input" required value={policyName} onChange={(event) => setPolicyName(event.target.value)} placeholder="Policy name" />
            <select className="input" value={policyEnvironment} onChange={(event) => setPolicyEnvironment(event.target.value)}><option value="">All environments</option>{environments.map((environment) => <option key={environment.id} value={environment.id}>{environment.name}</option>)}</select>
            <input className="input" value={policyPath} onChange={(event) => setPolicyPath(event.target.value)} placeholder="/path" />
            <select className="input" required value={approver} onChange={(event) => setApprover(event.target.value)}><option value="">Select approver</option>{members.map((member) => <option key={member.user_id} value={`user:${member.user_id}`}>{member.email}</option>)}{roles.map((role) => <option key={role.id} value={`role:${role.id}`}>Role: {role.name}</option>)}</select>
            <select className="input" value={secondApprover} onChange={(event) => setSecondApprover(event.target.value)}><option value="">No second step</option>{members.map((member) => <option key={member.user_id} value={`user:${member.user_id}`}>{member.email}</option>)}{roles.map((role) => <option key={role.id} value={`role:${role.id}`}>Role: {role.name}</option>)}</select>
            <button className="btn btn-primary" disabled={busy}>Protect changes</button>
          </form>
          {policies.map((policy) => <div className="governance-row" key={policy.id}><div><strong>{policy.name}</strong><div className="text-muted">{policy.path} · {policy.steps.length} step(s) · {policy.actions.join(', ')}</div></div><span className="badge">{policy.enabled ? 'enabled' : 'disabled'}</span></div>)}
        </div></div>

        {retention && <div className="settings-section"><h3 className="settings-section-title">Retention and recovery</h3><div className="card settings-card">
          <div className="governance-form"><label>Versions<input className="input" type="number" min="1" value={retention.retain_versions} onChange={(event) => setRetention({ ...retention, retain_versions: Number(event.target.value) })} /></label><label>Days<input className="input" type="number" value={retention.retain_days ?? ''} onChange={(event) => setRetention({ ...retention, retain_days: inputNumber(event.target.value) })} /></label><label>Archive deleted after days<input className="input" type="number" value={retention.archive_deleted_after_days ?? ''} onChange={(event) => setRetention({ ...retention, archive_deleted_after_days: inputNumber(event.target.value) })} /></label><button className="btn btn-secondary" disabled={busy} onClick={saveRetention}>Save retention</button></div>
          <div className="governance-form"><select className="input" value={recoveryEnvironment} onChange={(event) => setRecoveryEnvironment(event.target.value)}><option value="">Environment</option>{environments.map((environment) => <option key={environment.id} value={environment.id}>{environment.name}</option>)}</select><input className="input" type="datetime-local" value={recoveryAt} onChange={(event) => setRecoveryAt(event.target.value)} /><input className="input" value={recoveryPath} onChange={(event) => setRecoveryPath(event.target.value)} /><button className="btn btn-secondary" disabled={busy || !recoveryAt || !recoveryEnvironment} onClick={() => recover(false)}>Preview</button><button className="btn btn-danger" disabled={busy || !recoveryResult || recoveryResult.dry_run === false} onClick={() => recover(true)}>Apply</button></div>
          {recoveryResult && <p className="text-muted">{recoveryResult.changed} change(s): {recoveryResult.items.map((item) => `${item.action} ${item.path}/${item.key}`).join(', ') || 'none'}</p>}
        </div></div>}
      </>}
    </div>
  );
}
