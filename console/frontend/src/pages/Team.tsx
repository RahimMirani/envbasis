import { useEffect, useState } from 'react';
import { Shield, UserPlus, UserX } from 'lucide-react';
import { useOutletContext } from 'react-router-dom';
import DashboardLoader from '../components/DashboardLoader';
import Modal from '../components/Modal';
import { useAuth } from '../auth/useAuth';
import {
  inviteMember,
  listMembers,
  listProjectInvitations,
  revokeMember,
  revokeProjectInvitation,
  updateMemberSecretAccess,
} from '../lib/api';
import { formatDate } from '../lib/format';
import { getUserDisplayName, getUserInitials } from '../lib/user';
import type { Project, Member, ApiErrorDetails, ProjectInvitation } from '../types/api';
import { ApiError } from '../lib/api';

interface OutletContextType {
  currentProject: Project;
  canManageProject: boolean;
  onMemberCountChanged: (delta: number) => void;
}

interface RevokeConflict {
  member: Member;
  detail: {
    code?: string;
    message?: string;
    shared_tokens?: Array<{ id: string; name: string }>;
    revealed_shared_tokens?: Array<{ id: string; name: string }>;
  };
}

function formatRole(role: string | null | undefined): string {
  return role ? role.charAt(0).toUpperCase() + role.slice(1) : 'Member';
}

function formatInviteError(error: ApiError | Error | null): string {
  if (!error) {
    return 'Failed to invite member.';
  }

  if (error instanceof ApiError) {
    if (error.status === 429) {
      const d = (error.details as ApiErrorDetails)?.detail;
      if (typeof d === 'object' && d && 'message' in d && typeof (d as { message?: string }).message === 'string') {
        return (d as { message: string }).message;
      }
      return error.message || 'Too many invite emails sent. Please wait for the cooldown.';
    }

    if (error.status === 409) {
      return error.message || 'This user already has access to the project.';
    }
  }

  return error.message || 'Failed to invite member.';
}

export default function TeamPage() {
  const { currentProject, canManageProject, onMemberCountChanged } =
    useOutletContext<OutletContextType>();
  const { accessToken, apiConfigError } = useAuth();
  const [members, setMembers] = useState<Member[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showInvite, setShowInvite] = useState(false);
  const [inviteEmail, setInviteEmail] = useState('');
  const [inviteCanPushPullSecrets, setInviteCanPushPullSecrets] = useState(true);
  const [inviteError, setInviteError] = useState<string | null>(null);
  const [isInviting, setIsInviting] = useState(false);
  const [activeMemberEmail, setActiveMemberEmail] = useState<string | null>(null);
  const [revokeConflict, setRevokeConflict] = useState<RevokeConflict | null>(null);
  const [pendingInvites, setPendingInvites] = useState<ProjectInvitation[]>([]);
  const [revokingInviteId, setRevokingInviteId] = useState<string | null>(null);

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

    async function loadMembers() {
      setIsLoading(true);
      setError(null);

      try {
        const [response, invites] = await Promise.all([
          listMembers(currentProject.id, accessToken!, {
            signal: controller.signal,
          }),
          canManageProject
            ? listProjectInvitations(currentProject.id, accessToken!, {
                signal: controller.signal,
              })
            : Promise.resolve([] as ProjectInvitation[]),
        ]);

        if (!isActive) {
          return;
        }

        setMembers(response);
        setPendingInvites(invites);
      } catch (loadError) {
        if (!isActive || controller.signal.aborted) {
          return;
        }

        setError((loadError as Error).message || 'Failed to load team members.');
        setMembers([]);
        setPendingInvites([]);
      } finally {
        if (isActive) {
          setIsLoading(false);
        }
      }
    }

    void loadMembers();

    return () => {
      isActive = false;
      controller.abort();
    };
  }, [accessToken, apiConfigError, currentProject.id, canManageProject]);

  const closeInviteModal = () => {
    if (isInviting) {
      return;
    }

    setShowInvite(false);
    setInviteEmail('');
    setInviteCanPushPullSecrets(true);
    setInviteError(null);
  };

  const handleInviteMember = async () => {
    const email = inviteEmail.trim().toLowerCase();
    if (!email) {
      setInviteError('Member email is required.');
      return;
    }

    setIsInviting(true);
    setInviteError(null);

    try {
      const result = await inviteMember(currentProject.id, accessToken!, {
        email,
        role: 'member',
        can_push_pull_secrets: inviteCanPushPullSecrets,
      });

      setPendingInvites((cur) => {
        const others = cur.filter((p) => p.id !== result.invitation.id);
        return [result.invitation, ...others];
      });
      if (!result.email_sent && result.message) {
        setError(result.message);
      }
      setInviteError(null);
      setShowInvite(false);
      setInviteEmail('');
      setInviteCanPushPullSecrets(true);
    } catch (inviteErrorValue) {
      setInviteError(formatInviteError(inviteErrorValue as ApiError));
    } finally {
      setIsInviting(false);
    }
  };

  const handleToggleSecretAccess = async (member: Member) => {
    setActiveMemberEmail(member.email);
    setError(null);

    try {
      const updatedMember = await updateMemberSecretAccess(currentProject.id, accessToken!, {
        email: member.email,
        can_push_pull_secrets: !member.can_push_pull_secrets,
      });

      setMembers((currentMembers) =>
        currentMembers.map((currentMember) =>
          currentMember.user_id === updatedMember.user_id ? updatedMember : currentMember
        )
      );
    } catch (toggleError) {
      setError((toggleError as Error).message || 'Failed to update secret access.');
    } finally {
      setActiveMemberEmail(null);
    }
  };

  const handleRevokePendingInvite = async (invitation: ProjectInvitation) => {
    if (!accessToken) {
      return;
    }
    setRevokingInviteId(invitation.id);
    setError(null);
    try {
      await revokeProjectInvitation(currentProject.id, invitation.id, accessToken);
      setPendingInvites((cur) => cur.filter((p) => p.id !== invitation.id));
    } catch (revErr) {
      setError((revErr as Error).message || 'Failed to revoke invitation.');
    } finally {
      setRevokingInviteId(null);
    }
  };

  const attemptRevokeMember = async (member: Member, sharedTokenAction: string | null = null) => {
    setActiveMemberEmail(member.email);
    setError(null);

    try {
      await revokeMember(currentProject.id, accessToken!, {
        email: member.email,
        ...(sharedTokenAction ? { shared_token_action: sharedTokenAction } : {}),
      });

      setMembers((currentMembers) =>
        currentMembers.filter((currentMember) => currentMember.user_id !== member.user_id)
      );
      onMemberCountChanged(-1);
      setRevokeConflict(null);
    } catch (revokeErrorValue) {
      const apiError = revokeErrorValue as ApiError;
      const detail = (apiError.details as ApiErrorDetails)?.detail;
      if (
        detail?.code === 'shared_runtime_token_confirmation_required' ||
        detail?.code === 'revealed_runtime_tokens_require_revocation'
      ) {
        setRevokeConflict({
          member,
          detail,
        });
      } else {
        setError(apiError.message || 'Failed to revoke member.');
      }
    } finally {
      setActiveMemberEmail(null);
    }
  };

  return (
    <div className="team-page animate-in">
      <div className="page-header">
        <div>
          <h1 className="page-heading">Team</h1>
          <p className="page-subtitle">
            Manage who has access to this project's secrets and environments.
          </p>
        </div>
        <div className="page-header-actions">
          <button
            className="btn btn-primary"
            onClick={() => setShowInvite(true)}
            id="invite-member-btn"
            disabled={!canManageProject}
          >
            <UserPlus size={14} />
            Invite Member
          </button>
        </div>
      </div>

      {!canManageProject && (
        <p className="team-note">
          Only project owners can invite members, change secret access, or revoke access.
        </p>
      )}

      {error && (
        <div className="auth-status auth-status-error" role="alert">
          <span>{error}</span>
        </div>
      )}

      {canManageProject && pendingInvites.length > 0 && (
        <div className="card" style={{ marginBottom: '1rem' }}>
          <h3 className="page-subtitle" style={{ margin: '0 0 12px' }}>
            Pending invitations
          </h3>
          <div className="table-wrapper">
            <table>
              <thead>
                <tr>
                  <th>Email</th>
                  <th>Secrets access</th>
                  <th>Expires</th>
                  <th>Sent</th>
                  <th style={{ width: 100 }}>Actions</th>
                </tr>
              </thead>
              <tbody>
                {pendingInvites.map((inv) => (
                  <tr key={inv.id}>
                    <td className="mono">{inv.email}</td>
                    <td>{inv.can_push_pull_secrets ? 'Yes' : 'No'}</td>
                    <td className="text-secondary">{formatDate(inv.expires_at)}</td>
                    <td className="text-secondary">{inv.send_count}</td>
                    <td>
                      <button
                        type="button"
                        className="btn btn-ghost btn-sm btn-danger-subtle"
                        onClick={() => handleRevokePendingInvite(inv)}
                        disabled={revokingInviteId === inv.id}
                      >
                        Revoke
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {pendingInvites.some((p) => p.cooldown_until) && (
            <p className="text-secondary" style={{ fontSize: 13, marginTop: 8 }}>
              After two invite emails to the same address, this project must wait 5 days before sending
              more.
            </p>
          )}
        </div>
      )}

      {isLoading ? (
        <DashboardLoader compact title="Loading team" description="Fetching project members." />
      ) : members.length === 0 ? (
        <div className="empty-state">
          <h3>No members yet</h3>
          <p>Invite teammates by email. They will accept from the email link or their notifications.</p>
          {canManageProject && (
            <button className="btn btn-primary" onClick={() => setShowInvite(true)}>
              <UserPlus size={14} />
              Invite Member
            </button>
          )}
        </div>
      ) : (
        <div className="card">
          <div className="table-wrapper">
            <table id="team-table">
              <thead>
                <tr>
                  <th>Member</th>
                  <th>Role</th>
                  <th>Secrets Access</th>
                  <th>Joined</th>
                  <th style={{ width: 120 }}>Actions</th>
                </tr>
              </thead>
              <tbody>
                {members.map((member) => {
                  const isOwner = member.role === 'owner';
                  const isBusy = activeMemberEmail === member.email;

                  return (
                    <tr key={member.user_id}>
                      <td>
                        <div className="member-cell">
                          <div className="member-avatar">{getUserInitials(member)}</div>
                          <div className="member-info">
                            <span className="member-name">{getUserDisplayName(member)}</span>
                            <span className="member-email">{member.email}</span>
                          </div>
                        </div>
                      </td>
                      <td>
                        <span className={`badge ${isOwner ? 'badge-accent' : 'badge-neutral'}`}>
                          {isOwner && <Shield size={10} />}
                          {formatRole(member.role)}
                        </span>
                      </td>
                      <td>
                        <button
                          className={`btn btn-sm ${member.can_push_pull_secrets ? 'btn-secondary' : 'btn-ghost'}`}
                          onClick={() => handleToggleSecretAccess(member)}
                          disabled={!canManageProject || isOwner || isBusy}
                        >
                          {member.can_push_pull_secrets ? 'Enabled' : 'Disabled'}
                        </button>
                      </td>
                      <td className="text-secondary">{formatDate(member.joined_at)}</td>
                      <td>
                        {!isOwner && (
                          <button
                            className="btn btn-ghost btn-icon btn-sm btn-danger-subtle"
                            data-tooltip="Revoke Access"
                            aria-label="Revoke access"
                            onClick={() => attemptRevokeMember(member)}
                            disabled={!canManageProject || isBusy}
                          >
                            <UserX size={14} />
                          </button>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      <Modal
        isOpen={showInvite}
        onClose={closeInviteModal}
        title="Invite Team Member"
        footer={
          <>
            <button
              className="btn btn-secondary"
              onClick={closeInviteModal}
              disabled={isInviting}
            >
              Cancel
            </button>
            <button
              className="btn btn-primary"
              onClick={handleInviteMember}
              id="send-invite-btn"
              disabled={isInviting}
            >
              <UserPlus size={14} />
              {isInviting ? 'Inviting...' : 'Invite Member'}
            </button>
          </>
        }
      >
        <div className="form-group">
          <label htmlFor="invite-email-input">Email address</label>
          <input
            id="invite-email-input"
            className="input"
            type="email"
            placeholder="teammate@company.com"
            value={inviteEmail}
            onChange={(e) => setInviteEmail(e.target.value)}
            disabled={isInviting}
          />
        </div>
        <div className="team-checkbox-row">
          <input
            id="invite-secret-access"
            type="checkbox"
            checked={inviteCanPushPullSecrets}
            onChange={(event) => setInviteCanPushPullSecrets(event.target.checked)}
            disabled={isInviting}
          />
          <label htmlFor="invite-secret-access">
            Allow this member to push and pull secrets.
          </label>
        </div>
        {inviteError && (
          <p className="team-error" role="alert">
            {inviteError}
          </p>
        )}
        <p className="invite-hint">
          The recipient gets an email with a link (if SMTP is configured). They can also see pending
          invites in their dashboard notifications.
        </p>
      </Modal>

      <Modal
        isOpen={Boolean(revokeConflict)}
        onClose={() => setRevokeConflict(null)}
        title="Revoke Member Access"
        footer={
          revokeConflict?.detail?.code === 'shared_runtime_token_confirmation_required' ? (
            <>
              <button className="btn btn-secondary" onClick={() => setRevokeConflict(null)}>
                Cancel
              </button>
              <button
                className="btn btn-secondary"
                onClick={() => attemptRevokeMember(revokeConflict.member, 'keep_active')}
              >
                Keep Tokens Active
              </button>
              <button
                className="btn btn-danger"
                onClick={() => attemptRevokeMember(revokeConflict.member, 'revoke_tokens')}
              >
                Revoke Tokens Too
              </button>
            </>
          ) : (
            <>
              <button className="btn btn-secondary" onClick={() => setRevokeConflict(null)}>
                Cancel
              </button>
              <button
                className="btn btn-danger"
                onClick={() =>
                  revokeConflict && attemptRevokeMember(revokeConflict.member, 'revoke_tokens')
                }
              >
                Revoke Tokens Too
              </button>
            </>
          )
        }
      >
        {revokeConflict && (
          <>
            <p className="team-modal-copy">{revokeConflict.detail.message}</p>
            {Array.isArray(revokeConflict.detail.shared_tokens) &&
              revokeConflict.detail.shared_tokens.length > 0 && (
                <div className="team-token-list">
                  {revokeConflict.detail.shared_tokens.map((token) => (
                    <span className="badge badge-neutral" key={token.id}>
                      {token.name}
                    </span>
                  ))}
                </div>
              )}
            {Array.isArray(revokeConflict.detail.revealed_shared_tokens) &&
              revokeConflict.detail.revealed_shared_tokens.length > 0 && (
                <p className="team-error">
                  Revealed tokens:{' '}
                  {revokeConflict.detail.revealed_shared_tokens.map((token) => token.name).join(', ')}
                </p>
              )}
          </>
        )}
      </Modal>
    </div>
  );
}
