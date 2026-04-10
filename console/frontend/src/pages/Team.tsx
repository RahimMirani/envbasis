import { useEffect, useState } from 'react';
import { Shield, UserPlus, UserX } from 'lucide-react';
import { useOutletContext } from 'react-router-dom';
import Checkbox from '../components/Checkbox';
import ConfirmDialog from '../components/ConfirmDialog';
import SectionLoader from '../components/SectionLoader';
import Modal from '../components/Modal';
import { useAuth } from '../auth/useAuth';
import {
  bulkRevokeMembers,
  inviteMember,
  listMembers,
  listProjectInvitations,
  revokeMember,
  revokeProjectInvitation,
  updateMemberSecretAccess,
} from '../lib/api';
import { formatDate, formatRelativeTime } from '../lib/format';
import type { ProjectPageCacheApi } from '../lib/projectPageCache';
import { getUserDisplayName, getUserInitials } from '../lib/user';
import type { Project, Member, ApiErrorDetails, ProjectInvitation } from '../types/api';
import { ApiError } from '../lib/api';

interface OutletContextType {
  currentProject: Project;
  canManageProject: boolean;
  onMemberCountChanged: (delta: number) => void;
  pageCache: ProjectPageCacheApi;
}

interface TeamCacheEntry {
  members: Member[];
  pendingInvites: ProjectInvitation[];
}

interface RevokeConflict {
  members: Member[];
  detail: {
    code?: string;
    message?: string;
    shared_tokens?: Array<{ id: string; name: string }>;
    revealed_shared_tokens?: Array<{ id: string; name: string }>;
    members?: Array<{
      email: string;
      shared_tokens: Array<{ id: string; name: string }>;
      revealed_shared_tokens: Array<{ id: string; name: string }>;
    }>;
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

function getInviteCooldownMs(cooldownUntil: string | null, nowMs: number): number {
  if (!cooldownUntil) {
    return 0;
  }

  return Math.max(0, new Date(cooldownUntil).getTime() - nowMs);
}

function formatDuration(ms: number): string {
  const totalMinutes = Math.ceil(ms / 60000);
  if (totalMinutes <= 1) {
    return 'under 1 minute';
  }

  const days = Math.floor(totalMinutes / (24 * 60));
  const hours = Math.floor((totalMinutes % (24 * 60)) / 60);
  const minutes = totalMinutes % 60;

  if (days > 0) {
    if (hours > 0) {
      return `${days}d ${hours}h`;
    }
    return `${days}d`;
  }

  if (hours > 0) {
    if (minutes > 0) {
      return `${hours}h ${minutes}m`;
    }
    return `${hours}h`;
  }

  return `${minutes}m`;
}

function formatInviteLastSent(lastSentAt: string | null): string {
  if (!lastSentAt) {
    return 'Not sent yet';
  }

  return formatRelativeTime(lastSentAt);
}

export default function TeamPage() {
  const { currentProject, canManageProject, onMemberCountChanged, pageCache } =
    useOutletContext<OutletContextType>();
  const { accessToken, apiConfigError } = useAuth();
  const teamCacheKey = `team:${currentProject.id}`;
  const cachedTeam = pageCache.get<TeamCacheEntry>(teamCacheKey);
  const [members, setMembers] = useState<Member[]>(() => cachedTeam?.members ?? []);
  const [isLoading, setIsLoading] = useState(() => !cachedTeam);
  const [error, setError] = useState<string | null>(null);
  const [showInvite, setShowInvite] = useState(false);
  const [inviteEmail, setInviteEmail] = useState('');
  const [inviteCanPushPullSecrets, setInviteCanPushPullSecrets] = useState(true);
  const [inviteError, setInviteError] = useState<string | null>(null);
  const [isInviting, setIsInviting] = useState(false);
  const [activeMemberEmail, setActiveMemberEmail] = useState<string | null>(null);
  const [revokeConflict, setRevokeConflict] = useState<RevokeConflict | null>(null);
  const [keepActiveConfirm, setKeepActiveConfirm] = useState(false);
  const [pendingInvites, setPendingInvites] = useState<ProjectInvitation[]>(() => cachedTeam?.pendingInvites ?? []);
  const [revokingInviteId, setRevokingInviteId] = useState<string | null>(null);
  const [resendingInviteId, setResendingInviteId] = useState<string | null>(null);
  const [selectedInviteIds, setSelectedInviteIds] = useState<string[]>([]);
  const [isBulkRevokingInvites, setIsBulkRevokingInvites] = useState(false);
  const [showBulkRevokeInvitesConfirm, setShowBulkRevokeInvitesConfirm] = useState(false);
  const [selectedMemberIds, setSelectedMemberIds] = useState<string[]>([]);
  const [bulkMembersPendingRevoke, setBulkMembersPendingRevoke] = useState<Member[]>([]);
  const [isBulkRevoking, setIsBulkRevoking] = useState(false);
  const [nowMs, setNowMs] = useState(() => Date.now());

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
      if (cachedTeam) {
        setIsLoading(false);
        return;
      }

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
        pageCache.set<TeamCacheEntry>(teamCacheKey, {
          members: response,
          pendingInvites: invites,
        });
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
  }, [accessToken, apiConfigError, cachedTeam, canManageProject, currentProject.id, pageCache, teamCacheKey]);

  useEffect(() => {
    if (!isLoading && !error) {
      pageCache.set<TeamCacheEntry>(teamCacheKey, {
        members,
        pendingInvites,
      });
    }
  }, [error, isLoading, members, pageCache, pendingInvites, teamCacheKey]);

  useEffect(() => {
    setSelectedMemberIds((current) =>
      current.filter((memberId) => members.some((member) => member.user_id === memberId && member.role !== 'owner'))
    );
  }, [members]);

  useEffect(() => {
    setSelectedInviteIds((current) =>
      current.filter((id) => pendingInvites.some((inv) => inv.id === id))
    );
  }, [pendingInvites]);

  useEffect(() => {
    setNowMs(Date.now());
    const hasActiveCooldown = pendingInvites.some((inv) => getInviteCooldownMs(inv.cooldown_until, Date.now()) > 0);
    if (!hasActiveCooldown) {
      return undefined;
    }

    const interval = window.setInterval(() => {
      setNowMs(Date.now());
    }, 60000);

    return () => {
      window.clearInterval(interval);
    };
  }, [pendingInvites]);

  const selectedMembers = members.filter((member) => selectedMemberIds.includes(member.user_id));
  const revocableMembers = members.filter((member) => member.role !== 'owner');
  const allRevocableSelected =
    revocableMembers.length > 0 &&
    revocableMembers.every((member) => selectedMemberIds.includes(member.user_id));

  const selectedInvites = pendingInvites.filter((inv) => selectedInviteIds.includes(inv.id));
  const allInvitesSelected =
    pendingInvites.length > 0 &&
    pendingInvites.every((inv) => selectedInviteIds.includes(inv.id));

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

  const handleResendPendingInvite = async (invitation: ProjectInvitation) => {
    if (!accessToken) {
      return;
    }

    setResendingInviteId(invitation.id);
    setError(null);

    try {
      const result = await inviteMember(currentProject.id, accessToken, {
        email: invitation.email,
        role: 'member',
        can_push_pull_secrets: invitation.can_push_pull_secrets,
      });

      setPendingInvites((current) => {
        const others = current.filter((pendingInvite) => pendingInvite.id !== result.invitation.id);
        return [result.invitation, ...others];
      });

      if (!result.email_sent && result.message) {
        setError(result.message);
      }
    } catch (resendErrorValue) {
      setError(formatInviteError(resendErrorValue as ApiError));
    } finally {
      setResendingInviteId(null);
    }
  };

  const toggleInviteSelection = (inviteId: string) => {
    setSelectedInviteIds((current) =>
      current.includes(inviteId)
        ? current.filter((id) => id !== inviteId)
        : [...current, inviteId]
    );
  };

  const toggleSelectAllInvites = () => {
    if (allInvitesSelected) {
      setSelectedInviteIds([]);
    } else {
      setSelectedInviteIds(pendingInvites.map((inv) => inv.id));
    }
  };

  const handleBulkRevokeInvites = async () => {
    if (selectedInvites.length === 0) {
      setShowBulkRevokeInvitesConfirm(false);
      return;
    }
    setIsBulkRevokingInvites(true);
    setError(null);
    try {
      await Promise.all(
        selectedInvites.map((inv) =>
          revokeProjectInvitation(currentProject.id, inv.id, accessToken!)
        )
      );
      setPendingInvites((current) =>
        current.filter((inv) => !selectedInvites.some((s) => s.id === inv.id))
      );
      setSelectedInviteIds([]);
      setShowBulkRevokeInvitesConfirm(false);
    } catch (err) {
      setError((err as Error).message || 'Failed to revoke selected invitations.');
    } finally {
      setIsBulkRevokingInvites(false);
    }
  };

  const toggleMemberSelection = (memberId: string) => {
    setSelectedMemberIds((current) =>
      current.includes(memberId)
        ? current.filter((id) => id !== memberId)
        : [...current, memberId]
    );
  };

  const toggleSelectAllMembers = () => {
    if (allRevocableSelected) {
      setSelectedMemberIds([]);
      return;
    }

    setSelectedMemberIds(revocableMembers.map((member) => member.user_id));
  };

  const attemptRevokeMembers = async (
    revokeMembers: Member[],
    sharedTokenAction: string | null = null
  ) => {
    if (revokeMembers.length === 0) {
      return;
    }

    const isBulk = revokeMembers.length > 1;
    if (isBulk) {
      setIsBulkRevoking(true);
      setBulkMembersPendingRevoke([]);
    } else {
      setActiveMemberEmail(revokeMembers[0].email);
    }
    setError(null);

    try {
      if (isBulk) {
        await bulkRevokeMembers(currentProject.id, accessToken!, {
          emails: revokeMembers.map((member) => member.email),
          ...(sharedTokenAction ? { shared_token_action: sharedTokenAction } : {}),
        });
      } else {
        await revokeMember(currentProject.id, accessToken!, {
          email: revokeMembers[0].email,
          ...(sharedTokenAction ? { shared_token_action: sharedTokenAction } : {}),
        });
      }

      setMembers((currentMembers) =>
        currentMembers.filter(
          (currentMember) =>
            !revokeMembers.some((revokeMemberItem) => revokeMemberItem.user_id === currentMember.user_id)
        )
      );
      setSelectedMemberIds((current) =>
        current.filter(
          (memberId) => !revokeMembers.some((revokeMemberItem) => revokeMemberItem.user_id === memberId)
        )
      );
      onMemberCountChanged(-revokeMembers.length);
      setRevokeConflict(null);
      setKeepActiveConfirm(false);
    } catch (revokeErrorValue) {
      const apiError = revokeErrorValue as ApiError;
      const detail = (apiError.details as ApiErrorDetails)?.detail;
      if (detail?.code === 'shared_runtime_token_confirmation_required') {
        setRevokeConflict({
          members: revokeMembers,
          detail,
        });
      } else {
        setError(apiError.message || 'Failed to revoke member.');
      }
    } finally {
      setIsBulkRevoking(false);
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
            className="btn btn-danger"
            onClick={() => setBulkMembersPendingRevoke(selectedMembers)}
            disabled={!canManageProject || selectedMembers.length === 0 || isBulkRevoking}
          >
            <UserX size={14} />
            Revoke Selected
          </button>
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
        <div className="card pending-invites-card">
          <div className="pending-invites-header">
            <span className="pending-invites-title">Pending Invitations</span>
            <span className="badge badge-neutral">{pendingInvites.length}</span>
            {selectedInvites.length > 0 && (
              <button
                className="btn btn-danger btn-sm"
                style={{ marginLeft: 'auto' }}
                onClick={() => setShowBulkRevokeInvitesConfirm(true)}
                disabled={isBulkRevokingInvites}
              >
                <UserX size={13} />
                Revoke {selectedInvites.length} selected
              </button>
            )}
          </div>
          <div className="table-wrapper">
            <table>
              <thead>
                <tr>
                  <th style={{ width: 40 }}>
                    <Checkbox
                      checked={allInvitesSelected}
                      indeterminate={selectedInviteIds.length > 0 && !allInvitesSelected}
                      onChange={toggleSelectAllInvites}
                      aria-label="Select all invitations"
                      disabled={isBulkRevokingInvites}
                    />
                  </th>
                  <th>Recipient</th>
                  <th>Secrets access</th>
                  <th>Delivery</th>
                  <th>Expires</th>
                  <th style={{ width: 180 }}>Actions</th>
                </tr>
              </thead>
              <tbody>
                {pendingInvites.map((inv) => {
                  const cooldownMs = getInviteCooldownMs(inv.cooldown_until, nowMs);
                  const cooldownActive = cooldownMs > 0;
                  const isBusy =
                    revokingInviteId === inv.id || resendingInviteId === inv.id || isBulkRevokingInvites;

                  return (
                    <tr key={inv.id}>
                      <td className="table-checkbox-cell">
                        <Checkbox
                          checked={selectedInviteIds.includes(inv.id)}
                          onChange={() => toggleInviteSelection(inv.id)}
                          aria-label={`Select invitation for ${inv.email}`}
                          disabled={isBusy}
                        />
                      </td>
                      <td className="mono">{inv.email}</td>
                      <td>
                        <span className={`badge ${inv.can_push_pull_secrets ? 'badge-success' : 'badge-neutral'}`}>
                          {inv.can_push_pull_secrets ? 'Yes' : 'No'}
                        </span>
                      </td>
                      <td>
                        <div className="team-invite-delivery">
                          <span className="team-invite-meta">
                            Sent {inv.send_count} email{inv.send_count === 1 ? '' : 's'}
                          </span>
                          <span className="team-invite-meta">
                            Last sent {formatInviteLastSent(inv.last_sent_at)}
                          </span>
                          <span className={cooldownActive ? 'team-invite-cooldown' : 'team-invite-meta'}>
                            {cooldownActive ? `Resend in ${formatDuration(cooldownMs)}` : 'Ready to resend'}
                          </span>
                        </div>
                      </td>
                      <td className="text-secondary">{formatDate(inv.expires_at)}</td>
                      <td>
                        <div className="team-invite-actions">
                          <button
                            type="button"
                            className="btn btn-ghost btn-sm"
                            onClick={() => handleResendPendingInvite(inv)}
                            disabled={isBusy || cooldownActive}
                          >
                            {resendingInviteId === inv.id ? 'Sending...' : 'Resend'}
                          </button>
                          <button
                            type="button"
                            className="btn btn-ghost btn-sm btn-danger-subtle"
                            onClick={() => handleRevokePendingInvite(inv)}
                            disabled={isBusy}
                          >
                            {revokingInviteId === inv.id ? 'Revoking...' : 'Revoke'}
                          </button>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          {pendingInvites.some((p) => getInviteCooldownMs(p.cooldown_until, nowMs) > 0) && (
            <p className="pending-invites-note">
              After two invite emails to the same address, resend pauses for 5 days. The delivery
              column shows the remaining cooldown and the last time an invite email was sent.
            </p>
          )}
        </div>
      )}

      {isLoading ? (
        <SectionLoader label="Loading team" />
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
                  <th style={{ width: 40 }}>
                    <Checkbox
                      checked={allRevocableSelected}
                      indeterminate={selectedMemberIds.length > 0 && !allRevocableSelected}
                      onChange={toggleSelectAllMembers}
                      aria-label="Select all members"
                      disabled={!canManageProject || isBulkRevoking}
                    />
                  </th>
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
                  const isBusy = isBulkRevoking || activeMemberEmail === member.email;

                  return (
                    <tr key={member.user_id}>
                      <td className="table-checkbox-cell">
                        {!isOwner && (
                          <Checkbox
                            checked={selectedMemberIds.includes(member.user_id)}
                            onChange={() => toggleMemberSelection(member.user_id)}
                            aria-label={`Select member ${member.email}`}
                            disabled={!canManageProject || isBusy}
                          />
                        )}
                      </td>
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
                            onClick={() => {
                              void attemptRevokeMembers([member]);
                            }}
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
        onClose={() => {
          setRevokeConflict(null);
          setKeepActiveConfirm(false);
        }}
        title="Revoke Member Access"
        footer={
          keepActiveConfirm ? (
            <>
              <button
                className="btn btn-secondary"
                onClick={() => setKeepActiveConfirm(false)}
              >
                Back
              </button>
              <button
                className="btn btn-danger"
                onClick={() => revokeConflict && void attemptRevokeMembers(revokeConflict.members, 'keep_active')}
              >
                Yes, Keep Tokens Active
              </button>
            </>
          ) : (
            <>
              <button
                className="btn btn-secondary"
                onClick={() => {
                  setRevokeConflict(null);
                  setKeepActiveConfirm(false);
                }}
              >
                Cancel
              </button>
              <button
                className="btn btn-secondary"
                onClick={() => setKeepActiveConfirm(true)}
              >
                Keep Tokens Active
              </button>
              <button
                className="btn btn-danger"
                onClick={() => revokeConflict && void attemptRevokeMembers(revokeConflict.members, 'revoke_tokens')}
              >
                Revoke Tokens Too
              </button>
            </>
          )
        }
      >
        {revokeConflict && (
          <>
            {keepActiveConfirm ? (
              <p className="team-modal-copy">
                Are you sure you want to keep these tokens active? The member will lose access to the
                project, but the tokens will remain usable.
              </p>
            ) : (
              <>
                <p className="team-modal-copy">
                  {revokeConflict.members.length === 1
                    ? 'This member has shared runtime tokens. Choose whether to keep them active or revoke them.'
                    : 'Some selected members have shared runtime tokens. Choose whether to keep them active or revoke them.'}
                </p>
                {(revokeConflict.detail.members ??
                  [
                    {
                      email: revokeConflict.members[0]?.email || '',
                      shared_tokens: revokeConflict.detail.shared_tokens || [],
                      revealed_shared_tokens: revokeConflict.detail.revealed_shared_tokens || [],
                    },
                  ]).map((conflictMember) => (
                    <div key={conflictMember.email} className="team-bulk-conflict-block">
                      <p className="team-modal-copy" style={{ marginBottom: 6 }}>
                        <strong>{conflictMember.email}</strong>
                      </p>
                      {conflictMember.shared_tokens.length > 0 && (
                        <div className="team-token-list">
                          {conflictMember.shared_tokens.map((token) => (
                            <span className="badge badge-neutral" key={token.id}>
                              {token.name}
                            </span>
                          ))}
                        </div>
                      )}
                      {conflictMember.revealed_shared_tokens.length > 0 && (
                        <div className="team-token-list" style={{ marginTop: 12 }}>
                          {conflictMember.revealed_shared_tokens.map((token) => (
                            <span className="badge badge-warning" key={token.id}>
                              {token.name}
                            </span>
                          ))}
                        </div>
                      )}
                    </div>
                  ))}
              </>
            )}
          </>
        )}
      </Modal>
      <ConfirmDialog
        isOpen={bulkMembersPendingRevoke.length > 0}
        title="Revoke Selected Members"
        description={`Revoke access for ${bulkMembersPendingRevoke.length} selected member${bulkMembersPendingRevoke.length !== 1 ? 's' : ''}?`}
        confirmLabel="Revoke Members"
        onConfirm={() => {
          void attemptRevokeMembers(bulkMembersPendingRevoke);
        }}
        onClose={() => {
          if (!isBulkRevoking) {
            setBulkMembersPendingRevoke([]);
          }
        }}
        isBusy={isBulkRevoking}
      />
      <ConfirmDialog
        isOpen={showBulkRevokeInvitesConfirm}
        title="Revoke Selected Invitations"
        description={`Revoke ${selectedInvites.length} pending invitation${selectedInvites.length !== 1 ? 's' : ''}? The recipients will no longer be able to join.`}
        confirmLabel="Revoke Invitations"
        onConfirm={() => { void handleBulkRevokeInvites(); }}
        onClose={() => {
          if (!isBulkRevokingInvites) {
            setShowBulkRevokeInvitesConfirm(false);
          }
        }}
        isBusy={isBulkRevokingInvites}
      />
    </div>
  );
}
