import { useEffect, useRef, useState } from 'react';
import { Minus, Pencil, Plus, Shield, UserPlus, UserX, X } from 'lucide-react';
import { useOutletContext } from 'react-router-dom';
import Checkbox from '../components/Checkbox';
import ConfirmDialog from '../components/ConfirmDialog';
import SectionLoader from '../components/SectionLoader';
import Modal from '../components/Modal';
import { useAuth } from '../auth/useAuth';
import {
  bulkUpdateMemberPermissions,
  bulkRevokeMembers,
  inviteMember,
  listMembers,
  listProjectInvitations,
  revokeMember,
  revokeProjectInvitation,
  updateMemberPermissions,
} from '../lib/api';
import { formatDate, formatRelativeTime } from '../lib/format';
import type { ProjectPageCacheApi } from '../lib/projectPageCache';
import { getUserDisplayName, getUserInitials } from '../lib/user';
import type { Project, Member, ApiErrorDetails, ProjectInvitation } from '../types/api';
import { ApiError } from '../lib/api';

interface OutletContextType {
  currentProject: Project;
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

type PermissionKey = 'can_push_pull_secrets' | 'can_manage_runtime_tokens' | 'can_manage_team' | 'can_view_audit_logs';

type TriState = 'on' | 'off' | 'mixed';

const PERMISSIONS: { key: PermissionKey; label: string }[] = [
  { key: 'can_push_pull_secrets', label: 'Push/pull secrets' },
  { key: 'can_manage_runtime_tokens', label: 'Manage runtime tokens' },
  { key: 'can_manage_team', label: 'Manage team' },
  { key: 'can_view_audit_logs', label: 'View audit logs' },
];

function getTriState(members: Member[], key: PermissionKey): TriState {
  if (members.length === 0) return 'off';
  const count = members.filter((m) => m[key]).length;
  if (count === 0) return 'off';
  if (count === members.length) return 'on';
  return 'mixed';
}

function formatRole(role: string | null | undefined): string {
  return role ? role.charAt(0).toUpperCase() + role.slice(1) : 'Member';
}

function formatInviteError(error: ApiError | Error | null): string {
  if (!error) return 'Failed to invite member.';
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
  if (!cooldownUntil) return 0;
  return Math.max(0, new Date(cooldownUntil).getTime() - nowMs);
}

function formatDuration(ms: number): string {
  const totalMinutes = Math.ceil(ms / 60000);
  if (totalMinutes <= 1) return 'under 1 minute';
  const days = Math.floor(totalMinutes / (24 * 60));
  const hours = Math.floor((totalMinutes % (24 * 60)) / 60);
  const minutes = totalMinutes % 60;
  if (days > 0) return hours > 0 ? `${days}d ${hours}h` : `${days}d`;
  if (hours > 0) return minutes > 0 ? `${hours}h ${minutes}m` : `${hours}h`;
  return `${minutes}m`;
}

function formatInviteLastSent(lastSentAt: string | null): string {
  if (!lastSentAt) return 'Not sent yet';
  return formatRelativeTime(lastSentAt);
}

// ─── Permission popover (per-member edit) ────────────────────────────────────

interface PermissionPopoverProps {
  member: Member;
  disabled: boolean;
  onToggle: (member: Member, key: PermissionKey) => void;
}

function PermissionPopover({ member, disabled, onToggle }: PermissionPopoverProps) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return undefined;
    function handleClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener('mousedown', handleClick);
    return () => document.removeEventListener('mousedown', handleClick);
  }, [open]);

  return (
    <div className="perm-popover-root" ref={ref}>
      <button
        className="btn btn-ghost btn-icon btn-sm"
        aria-label="Edit permissions"
        data-tooltip="Edit permissions"
        disabled={disabled}
        onClick={() => setOpen((v) => !v)}
      >
        <Pencil size={13} />
      </button>
      {open && (
        <div className="perm-popover">
          <div className="perm-popover-title">Permissions</div>
          {PERMISSIONS.map(({ key, label }) => {
            const isOn = member[key];
            return (
              <label key={key} className={`perm-popover-row ${isOn ? 'perm-row-will-remove' : 'perm-row-will-add'}`}>
                <input
                  type="checkbox"
                  className="cb-input"
                  checked={isOn}
                  onChange={() => {
                    onToggle(member, key);
                    setOpen(false);
                  }}
                  disabled={disabled}
                />
                <span className="perm-popover-label">{label}</span>
                <span className={`perm-action-hint ${isOn ? 'perm-action-hint-remove' : 'perm-action-hint-add'}`}>
                  {isOn ? '− Remove' : '+ Grant'}
                </span>
              </label>
            );
          })}
        </div>
      )}
    </div>
  );
}

// ─── Bulk permission bar ──────────────────────────────────────────────────────

interface BulkPermBarProps {
  selectedMembers: Member[];
  isBusy: boolean;
  onBulkPermission: (key: PermissionKey, value: boolean) => void;
  onRevoke: () => void;
  onClear: () => void;
}

function BulkPermBar({ selectedMembers, isBusy, onBulkPermission, onRevoke, onClear }: BulkPermBarProps) {
  const [grantOpen, setGrantOpen] = useState(false);
  const [revokeOpen, setRevokeOpen] = useState(false);
  const grantRef = useRef<HTMLDivElement>(null);
  const revokeRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!grantOpen && !revokeOpen) return undefined;
    function handleClick(e: MouseEvent) {
      if (grantRef.current && !grantRef.current.contains(e.target as Node)) setGrantOpen(false);
      if (revokeRef.current && !revokeRef.current.contains(e.target as Node)) setRevokeOpen(false);
    }
    document.addEventListener('mousedown', handleClick);
    return () => document.removeEventListener('mousedown', handleClick);
  }, [grantOpen, revokeOpen]);

  return (
    <div className="bulk-bar">
      <span className="bulk-bar-count">{selectedMembers.length} selected</span>
      <div className="bulk-bar-divider" />

      {/* Grant */}
      <div className="perm-popover-root" ref={grantRef}>
        <button
          className="btn btn-secondary btn-sm"
          onClick={() => { setGrantOpen((v) => !v); setRevokeOpen(false); }}
          disabled={isBusy}
        >
          <Plus size={12} />
          Grant ▾
        </button>
        {grantOpen && (
          <div className="perm-popover perm-popover-bulk">
            <div className="perm-popover-title">Grant to selected</div>
            {PERMISSIONS.map(({ key, label }) => {
              const allHave = getTriState(selectedMembers, key) === 'on';
              return (
                <button
                  key={key}
                  type="button"
                  className={`perm-action-row perm-action-grant${allHave ? ' perm-action-noop' : ''}`}
                  onClick={() => { onBulkPermission(key, true); setGrantOpen(false); }}
                  disabled={isBusy || allHave}
                >
                  <span className="perm-popover-label">{label}</span>
                  {allHave && <span className="perm-mixed-hint">all have it</span>}
                </button>
              );
            })}
          </div>
        )}
      </div>

      {/* Revoke permission (not member) */}
      <div className="perm-popover-root" ref={revokeRef}>
        <button
          className="btn btn-secondary btn-sm"
          onClick={() => { setRevokeOpen((v) => !v); setGrantOpen(false); }}
          disabled={isBusy}
        >
          <Minus size={12} />
          Revoke ▾
        </button>
        {revokeOpen && (
          <div className="perm-popover perm-popover-bulk">
            <div className="perm-popover-title">Revoke from selected</div>
            {PERMISSIONS.map(({ key, label }) => {
              const noneHave = getTriState(selectedMembers, key) === 'off';
              return (
                <button
                  key={key}
                  type="button"
                  className={`perm-action-row perm-action-revoke${noneHave ? ' perm-action-noop' : ''}`}
                  onClick={() => { onBulkPermission(key, false); setRevokeOpen(false); }}
                  disabled={isBusy || noneHave}
                >
                  <span className="perm-popover-label">{label}</span>
                  {noneHave && <span className="perm-mixed-hint">none have it</span>}
                </button>
              );
            })}
          </div>
        )}
      </div>

      <button className="btn btn-danger btn-sm" onClick={onRevoke} disabled={isBusy}>
        <UserX size={13} />
        Revoke Access
      </button>
      <button className="btn btn-ghost btn-icon btn-sm" aria-label="Clear selection" onClick={onClear} disabled={isBusy}>
        <X size={14} />
      </button>
    </div>
  );
}

// ─── Main page ────────────────────────────────────────────────────────────────

export default function TeamPage() {
  const { currentProject, onMemberCountChanged, pageCache } =
    useOutletContext<OutletContextType>();
  const { accessToken, apiConfigError } = useAuth();
  const canManageTeam = currentProject.can_manage_team;
  const teamCacheKey = `team:${currentProject.id}`;
  const cachedTeam = pageCache.get<TeamCacheEntry>(teamCacheKey);

  const [members, setMembers] = useState<Member[]>(() => cachedTeam?.members ?? []);
  const [isLoading, setIsLoading] = useState(() => !cachedTeam);
  const [error, setError] = useState<string | null>(null);

  // invite
  const [showInvite, setShowInvite] = useState(false);
  const [inviteEmail, setInviteEmail] = useState('');
  const [invitePerms, setInvitePerms] = useState<Record<PermissionKey, boolean>>({
    can_push_pull_secrets: false,
    can_manage_runtime_tokens: false,
    can_manage_team: false,
    can_view_audit_logs: false,
  });
  const [inviteError, setInviteError] = useState<string | null>(null);
  const [isInviting, setIsInviting] = useState(false);

  // per-member edit
  const [activeMemberEmail, setActiveMemberEmail] = useState<string | null>(null);

  // revoke conflict modal
  const [revokeConflict, setRevokeConflict] = useState<RevokeConflict | null>(null);
  const [keepActiveConfirm, setKeepActiveConfirm] = useState(false);

  // pending invites
  const [pendingInvites, setPendingInvites] = useState<ProjectInvitation[]>(() => cachedTeam?.pendingInvites ?? []);
  const [revokingInviteId, setRevokingInviteId] = useState<string | null>(null);
  const [resendingInviteId, setResendingInviteId] = useState<string | null>(null);
  const [selectedInviteIds, setSelectedInviteIds] = useState<string[]>([]);
  const [isBulkRevokingInvites, setIsBulkRevokingInvites] = useState(false);
  const [showBulkRevokeInvitesConfirm, setShowBulkRevokeInvitesConfirm] = useState(false);

  // bulk member selection
  const [selectedMemberIds, setSelectedMemberIds] = useState<string[]>([]);
  const [bulkMembersPendingRevoke, setBulkMembersPendingRevoke] = useState<Member[]>([]);
  const [isBulkRevoking, setIsBulkRevoking] = useState(false);
  const [isBulkUpdatingPermissions, setIsBulkUpdatingPermissions] = useState(false);

  const [nowMs, setNowMs] = useState(() => Date.now());

  // ── load ──────────────────────────────────────────────────────────────────

  useEffect(() => {
    if (!accessToken) return undefined;
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
          listMembers(currentProject.id, accessToken!, { signal: controller.signal }),
          canManageTeam
            ? listProjectInvitations(currentProject.id, accessToken!, { signal: controller.signal })
            : Promise.resolve([] as ProjectInvitation[]),
        ]);
        if (!isActive) return;
        setMembers(response);
        setPendingInvites(invites);
        pageCache.set<TeamCacheEntry>(teamCacheKey, { members: response, pendingInvites: invites });
      } catch (loadError) {
        if (!isActive || controller.signal.aborted) return;
        setError((loadError as Error).message || 'Failed to load team members.');
        setMembers([]);
        setPendingInvites([]);
      } finally {
        if (isActive) setIsLoading(false);
      }
    }

    void loadMembers();
    return () => {
      isActive = false;
      controller.abort();
    };
  }, [accessToken, apiConfigError, cachedTeam, canManageTeam, currentProject.id, pageCache, teamCacheKey]);

  useEffect(() => {
    if (!isLoading && !error) {
      pageCache.set<TeamCacheEntry>(teamCacheKey, { members, pendingInvites });
    }
  }, [error, isLoading, members, pageCache, pendingInvites, teamCacheKey]);

  useEffect(() => {
    setSelectedMemberIds((cur) =>
      cur.filter((id) => members.some((m) => m.user_id === id && m.role !== 'owner'))
    );
  }, [members]);

  useEffect(() => {
    setSelectedInviteIds((cur) => cur.filter((id) => pendingInvites.some((inv) => inv.id === id)));
  }, [pendingInvites]);

  useEffect(() => {
    setNowMs(Date.now());
    const hasActiveCooldown = pendingInvites.some((inv) => getInviteCooldownMs(inv.cooldown_until, Date.now()) > 0);
    if (!hasActiveCooldown) return undefined;
    const interval = window.setInterval(() => setNowMs(Date.now()), 60000);
    return () => window.clearInterval(interval);
  }, [pendingInvites]);

  // ── derived ───────────────────────────────────────────────────────────────

  const selectedMembers = members.filter((m) => selectedMemberIds.includes(m.user_id));
  const revocableMembers = members.filter((m) => m.role !== 'owner');
  const allRevocableSelected =
    revocableMembers.length > 0 && revocableMembers.every((m) => selectedMemberIds.includes(m.user_id));
  const selectedInvites = pendingInvites.filter((inv) => selectedInviteIds.includes(inv.id));
  const allInvitesSelected =
    pendingInvites.length > 0 && pendingInvites.every((inv) => selectedInviteIds.includes(inv.id));

  // ── helpers ───────────────────────────────────────────────────────────────

  const applyUpdatedMembers = (updatedMembers: Member[]) => {
    const byId = new Map(updatedMembers.map((m) => [m.user_id, m]));
    setMembers((cur) => cur.map((m) => byId.get(m.user_id) ?? m));
  };

  // ── invite ────────────────────────────────────────────────────────────────

  const resetInviteForm = () => {
    setShowInvite(false);
    setInviteEmail('');
    setInvitePerms({
      can_push_pull_secrets: false,
      can_manage_runtime_tokens: false,
      can_manage_team: false,
      can_view_audit_logs: false,
    });
    setInviteError(null);
  };

  const closeInviteModal = () => {
    if (isInviting) return;
    resetInviteForm();
  };

  const handleInviteMember = async () => {
    const email = inviteEmail.trim().toLowerCase();
    if (!email) { setInviteError('Member email is required.'); return; }
    setIsInviting(true);
    setInviteError(null);
    try {
      const result = await inviteMember(currentProject.id, accessToken!, { email, role: 'member', ...invitePerms });
      setPendingInvites((cur) => {
        const others = cur.filter((p) => p.id !== result.invitation.id);
        return [result.invitation, ...others];
      });
      if (!result.email_sent && result.message) setError(result.message);
      resetInviteForm();
    } catch (inviteErrorValue) {
      setInviteError(formatInviteError(inviteErrorValue as ApiError));
    } finally {
      setIsInviting(false);
    }
  };

  // ── per-member permission toggle ──────────────────────────────────────────

  const handleTogglePermission = async (member: Member, key: PermissionKey) => {
    setActiveMemberEmail(member.email);
    setError(null);
    try {
      const updated = await updateMemberPermissions(currentProject.id, accessToken!, {
        email: member.email,
        [key]: !member[key],
      });
      applyUpdatedMembers([updated]);
    } catch (toggleError) {
      setError((toggleError as Error).message || 'Failed to update member permissions.');
    } finally {
      setActiveMemberEmail(null);
    }
  };

  // ── bulk permission update ────────────────────────────────────────────────

  const handleBulkPermission = async (key: PermissionKey, value: boolean) => {
    if (selectedMembers.length === 0) return;
    setIsBulkUpdatingPermissions(true);
    setError(null);
    try {
      const updated = await bulkUpdateMemberPermissions(currentProject.id, accessToken!, {
        emails: selectedMembers.map((m) => m.email),
        [key]: value,
      });
      applyUpdatedMembers(updated);
    } catch (permError) {
      setError((permError as Error).message || 'Failed to update permissions.');
    } finally {
      setIsBulkUpdatingPermissions(false);
    }
  };

  // ── pending invite actions ────────────────────────────────────────────────

  const handleRevokePendingInvite = async (invitation: ProjectInvitation) => {
    if (!accessToken) return;
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
    if (!accessToken) return;
    setResendingInviteId(invitation.id);
    setError(null);
    try {
      const result = await inviteMember(currentProject.id, accessToken, {
        email: invitation.email,
        role: 'member',
        can_push_pull_secrets: invitation.can_push_pull_secrets,
        can_manage_runtime_tokens: invitation.can_manage_runtime_tokens,
        can_manage_team: invitation.can_manage_team,
        can_view_audit_logs: invitation.can_view_audit_logs,
      });
      setPendingInvites((cur) => {
        const others = cur.filter((p) => p.id !== result.invitation.id);
        return [result.invitation, ...others];
      });
      if (!result.email_sent && result.message) setError(result.message);
    } catch (resendErr) {
      setError(formatInviteError(resendErr as ApiError));
    } finally {
      setResendingInviteId(null);
    }
  };

  const toggleInviteSelection = (inviteId: string) => {
    setSelectedInviteIds((cur) =>
      cur.includes(inviteId) ? cur.filter((id) => id !== inviteId) : [...cur, inviteId]
    );
  };

  const toggleSelectAllInvites = () => {
    setSelectedInviteIds(allInvitesSelected ? [] : pendingInvites.map((inv) => inv.id));
  };

  const handleBulkRevokeInvites = async () => {
    if (selectedInvites.length === 0) { setShowBulkRevokeInvitesConfirm(false); return; }
    setIsBulkRevokingInvites(true);
    setError(null);
    try {
      await Promise.all(selectedInvites.map((inv) => revokeProjectInvitation(currentProject.id, inv.id, accessToken!)));
      setPendingInvites((cur) => cur.filter((inv) => !selectedInvites.some((s) => s.id === inv.id)));
      setSelectedInviteIds([]);
      setShowBulkRevokeInvitesConfirm(false);
    } catch (err) {
      setError((err as Error).message || 'Failed to revoke selected invitations.');
    } finally {
      setIsBulkRevokingInvites(false);
    }
  };

  // ── member selection ──────────────────────────────────────────────────────

  const toggleMemberSelection = (memberId: string) => {
    setSelectedMemberIds((cur) =>
      cur.includes(memberId) ? cur.filter((id) => id !== memberId) : [...cur, memberId]
    );
  };

  const toggleSelectAllMembers = () => {
    setSelectedMemberIds(allRevocableSelected ? [] : revocableMembers.map((m) => m.user_id));
  };

  // ── member revoke ─────────────────────────────────────────────────────────

  const attemptRevokeMembers = async (revokeMembers: Member[], sharedTokenAction: string | null = null) => {
    if (revokeMembers.length === 0) return;
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
          emails: revokeMembers.map((m) => m.email),
          ...(sharedTokenAction ? { shared_token_action: sharedTokenAction } : {}),
        });
      } else {
        await revokeMember(currentProject.id, accessToken!, {
          email: revokeMembers[0].email,
          ...(sharedTokenAction ? { shared_token_action: sharedTokenAction } : {}),
        });
      }
      setMembers((cur) => cur.filter((m) => !revokeMembers.some((r) => r.user_id === m.user_id)));
      setSelectedMemberIds((cur) => cur.filter((id) => !revokeMembers.some((r) => r.user_id === id)));
      onMemberCountChanged(-revokeMembers.length);
      setRevokeConflict(null);
      setKeepActiveConfirm(false);
    } catch (revokeErrorValue) {
      const apiError = revokeErrorValue as ApiError;
      const detail = (apiError.details as ApiErrorDetails)?.detail;
      if (detail?.code === 'shared_runtime_token_confirmation_required') {
        setRevokeConflict({ members: revokeMembers, detail });
      } else {
        setError(apiError.message || 'Failed to revoke member.');
      }
    } finally {
      setIsBulkRevoking(false);
      setActiveMemberEmail(null);
    }
  };

  // ── render ────────────────────────────────────────────────────────────────

  const isBulkBusy = isBulkRevoking || isBulkUpdatingPermissions;

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
          {canManageTeam && (
            <button
              className="btn btn-primary"
              onClick={() => setShowInvite(true)}
              id="invite-member-btn"
            >
              <UserPlus size={14} />
              Invite Member
            </button>
          )}
        </div>
      </div>

      {/* Bulk action bar — shown only when members are selected */}
      {canManageTeam && selectedMembers.length > 0 && (
        <BulkPermBar
          selectedMembers={selectedMembers}
          isBusy={isBulkBusy}
          onBulkPermission={handleBulkPermission}
          onRevoke={() => setBulkMembersPendingRevoke(selectedMembers)}
          onClear={() => setSelectedMemberIds([])}
        />
      )}

      {!canManageTeam && (
        <p className="team-note">
          You can view project members, but only permitted managers can invite members, update permissions, or revoke access.
        </p>
      )}

      {error && (
        <div className="auth-status auth-status-error" role="alert">
          <span>{error}</span>
        </div>
      )}

      {/* Pending invitations */}
      {canManageTeam && pendingInvites.length > 0 && (
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
                  <th>Permissions</th>
                  <th>Delivery</th>
                  <th>Expires</th>
                  <th style={{ width: 180 }}>Actions</th>
                </tr>
              </thead>
              <tbody>
                {pendingInvites.map((inv) => {
                  const cooldownMs = getInviteCooldownMs(inv.cooldown_until, nowMs);
                  const cooldownActive = cooldownMs > 0;
                  const isBusy = revokingInviteId === inv.id || resendingInviteId === inv.id || isBulkRevokingInvites;
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
                        <div className="perm-badge-list">
                          {PERMISSIONS.filter(({ key }) => inv[key]).map(({ key, label }) => (
                            <span key={key} className="badge badge-neutral">{label}</span>
                          ))}
                          {PERMISSIONS.every(({ key }) => !inv[key]) && (
                            <span className="badge badge-neutral">View only</span>
                          )}
                        </div>
                      </td>
                      <td>
                        <div className="team-invite-delivery">
                          <span className="team-invite-meta">Sent {inv.send_count} email{inv.send_count === 1 ? '' : 's'}</span>
                          <span className="team-invite-meta">Last sent {formatInviteLastSent(inv.last_sent_at)}</span>
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
              After two invite emails to the same address, resend pauses for 5 days.
            </p>
          )}
        </div>
      )}

      {/* Members table */}
      {isLoading ? (
        <SectionLoader label="Loading team" />
      ) : members.length === 0 ? (
        <div className="empty-state">
          <h3>No members yet</h3>
          <p>Invite teammates by email. They will accept from the email link or their notifications.</p>
          {canManageTeam && (
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
                      disabled={!canManageTeam || isBulkBusy}
                    />
                  </th>
                  <th>Member</th>
                  <th>Role</th>
                  <th>Permissions</th>
                  <th>Joined</th>
                  <th style={{ width: 80 }}>Actions</th>
                </tr>
              </thead>
              <tbody>
                {members.map((member) => {
                  const isOwner = member.role === 'owner';
                  const isBusy = isBulkBusy || activeMemberEmail === member.email;
                  const activePerms = PERMISSIONS.filter(({ key }) => member[key]);

                  return (
                    <tr key={member.user_id}>
                      <td className="table-checkbox-cell">
                        {!isOwner && (
                          <Checkbox
                            checked={selectedMemberIds.includes(member.user_id)}
                            onChange={() => toggleMemberSelection(member.user_id)}
                            aria-label={`Select member ${member.email}`}
                            disabled={!canManageTeam || isBusy}
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
                        <div className="perm-badge-list">
                          {isOwner ? (
                            <span className="badge badge-accent">All permissions</span>
                          ) : activePerms.length > 0 ? (
                            activePerms.map(({ key, label }) => (
                              <span key={key} className="badge badge-neutral">{label}</span>
                            ))
                          ) : (
                            <span className="badge badge-neutral">View only</span>
                          )}
                        </div>
                      </td>
                      <td className="text-secondary">{formatDate(member.joined_at)}</td>
                      <td>
                        <div className="team-row-actions">
                          {!isOwner && canManageTeam && (
                            <PermissionPopover
                              member={member}
                              disabled={isBusy}
                              onToggle={handleTogglePermission}
                            />
                          )}
                          {!isOwner && canManageTeam && (
                            <button
                              className="btn btn-ghost btn-icon btn-sm btn-danger-subtle"
                              data-tooltip="Revoke Access"
                              aria-label="Revoke access"
                              onClick={() => void attemptRevokeMembers([member])}
                              disabled={isBusy}
                            >
                              <UserX size={14} />
                            </button>
                          )}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Invite modal */}
      <Modal
        isOpen={showInvite}
        onClose={closeInviteModal}
        title="Invite Team Member"
        footer={
          <>
            <button className="btn btn-secondary" onClick={closeInviteModal} disabled={isInviting}>
              Cancel
            </button>
            <button className="btn btn-primary" onClick={handleInviteMember} id="send-invite-btn" disabled={isInviting}>
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
        <div className="form-group" style={{ marginBottom: 0 }}>
          <label>Permissions</label>
          <div className="invite-perms-grid">
            {PERMISSIONS.map(({ key, label }) => (
              <label key={key} className="team-checkbox-row" style={{ marginBottom: 0 }}>
                <input
                  type="checkbox"
                  className="cb-input"
                  checked={invitePerms[key]}
                  onChange={(e) => setInvitePerms((cur) => ({ ...cur, [key]: e.target.checked }))}
                  disabled={isInviting}
                />
                <span>{label}</span>
              </label>
            ))}
          </div>
        </div>
        {inviteError && (
          <p className="team-error" role="alert">{inviteError}</p>
        )}
        <p className="invite-hint">
          The recipient gets an email with a link (if SMTP is configured). They can also see pending
          invites in their dashboard notifications.
        </p>
      </Modal>

      {/* Shared token conflict modal */}
      <Modal
        isOpen={Boolean(revokeConflict)}
        onClose={() => { setRevokeConflict(null); setKeepActiveConfirm(false); }}
        title="Revoke Member Access"
        footer={
          keepActiveConfirm ? (
            <>
              <button className="btn btn-secondary" onClick={() => setKeepActiveConfirm(false)}>Back</button>
              <button className="btn btn-danger" onClick={() => revokeConflict && void attemptRevokeMembers(revokeConflict.members, 'keep_active')}>
                Yes, Keep Tokens Active
              </button>
            </>
          ) : (
            <>
              <button className="btn btn-secondary" onClick={() => { setRevokeConflict(null); setKeepActiveConfirm(false); }}>Cancel</button>
              <button className="btn btn-secondary" onClick={() => setKeepActiveConfirm(true)}>Keep Tokens Active</button>
              <button className="btn btn-danger" onClick={() => revokeConflict && void attemptRevokeMembers(revokeConflict.members, 'revoke_tokens')}>
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
                {(revokeConflict.detail.members ?? [
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
                          <span className="badge badge-neutral" key={token.id}>{token.name}</span>
                        ))}
                      </div>
                    )}
                    {conflictMember.revealed_shared_tokens.length > 0 && (
                      <div className="team-token-list" style={{ marginTop: 12 }}>
                        {conflictMember.revealed_shared_tokens.map((token) => (
                          <span className="badge badge-warning" key={token.id}>{token.name}</span>
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
        onConfirm={() => void attemptRevokeMembers(bulkMembersPendingRevoke)}
        onClose={() => { if (!isBulkRevoking) setBulkMembersPendingRevoke([]); }}
        isBusy={isBulkRevoking}
      />
      <ConfirmDialog
        isOpen={showBulkRevokeInvitesConfirm}
        title="Revoke Selected Invitations"
        description={`Revoke ${selectedInvites.length} pending invitation${selectedInvites.length !== 1 ? 's' : ''}? The recipients will no longer be able to join.`}
        confirmLabel="Revoke Invitations"
        onConfirm={() => { void handleBulkRevokeInvites(); }}
        onClose={() => { if (!isBulkRevokingInvites) setShowBulkRevokeInvitesConfirm(false); }}
        isBusy={isBulkRevokingInvites}
      />
    </div>
  );
}
