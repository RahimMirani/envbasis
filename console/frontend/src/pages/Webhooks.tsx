import { useEffect, useRef, useState } from 'react';
import { Plus, Trash2, Copy, Check, Webhook as WebhookIcon } from 'lucide-react';
import { useOutletContext } from 'react-router-dom';
import ConfirmDialog from '../components/ConfirmDialog';
import DashboardLoader from '../components/DashboardLoader';
import Modal from '../components/Modal';
import { useAuth } from '../auth/useAuth';
import { listWebhooks, createWebhook, deleteWebhook, listWebhookEvents } from '../lib/api';
import { formatDate } from '../lib/format';
import type { Project, Webhook } from '../types/api';

interface OutletContextType {
  currentProject: Project;
  canManageProject: boolean;
}

const EVENT_LABELS: Record<string, string> = {
  'secret.created': 'Secret created',
  'secret.updated': 'Secret updated',
  'secret.deleted': 'Secret deleted',
  'secrets.pushed': 'Secrets pushed',
  'member.joined': 'Member joined',
  'member.revoked': 'Member revoked',
  'runtime_token.created': 'Runtime token created',
  'runtime_token.revoked': 'Runtime token revoked',
  '*': 'All events (wildcard)',
};

const DEFAULT_SUPPORTED_EVENTS = Object.keys(EVENT_LABELS);

export default function WebhooksPage() {
  const { currentProject, canManageProject } = useOutletContext<OutletContextType>();
  const { accessToken, apiConfigError } = useAuth();

  const [webhooks, setWebhooks] = useState<Webhook[]>([]);
  const [supportedEvents, setSupportedEvents] = useState<string[]>(DEFAULT_SUPPORTED_EVENTS);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Create
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [createUrl, setCreateUrl] = useState('');
  const [createEvents, setCreateEvents] = useState<string[]>([]);
  const [createError, setCreateError] = useState<string | null>(null);
  const [isCreating, setIsCreating] = useState(false);
  const urlInputRef = useRef<HTMLInputElement>(null);

  // Delete
  const [webhookPendingDelete, setWebhookPendingDelete] = useState<Webhook | null>(null);
  const [isDeleting, setIsDeleting] = useState(false);

  // Copy secret
  const [copiedId, setCopiedId] = useState<string | null>(null);

  useEffect(() => {
    if (!accessToken) return undefined;

    if (apiConfigError) {
      setError(apiConfigError);
      setIsLoading(false);
      return undefined;
    }

    if (!canManageProject) {
      setWebhooks([]);
      setSupportedEvents(DEFAULT_SUPPORTED_EVENTS);
      setError(null);
      setIsLoading(false);
      return undefined;
    }

    let isActive = true;
    const controller = new AbortController();

    async function load() {
      setIsLoading(true);
      setError(null);
      try {
        const [webhooksResult, eventsResult] = await Promise.allSettled([
          listWebhooks(currentProject.id, accessToken!, { signal: controller.signal }),
          listWebhookEvents(currentProject.id, accessToken!, { signal: controller.signal }),
        ]);
        if (!isActive) return;

        if (webhooksResult.status === 'rejected') {
          throw webhooksResult.reason;
        }

        setWebhooks(webhooksResult.value);
        setSupportedEvents(
          eventsResult.status === 'fulfilled' ? eventsResult.value : DEFAULT_SUPPORTED_EVENTS
        );
      } catch (err) {
        if (!isActive || controller.signal.aborted) return;
        setError((err as Error).message || 'Failed to load webhooks.');
      } finally {
        if (isActive) setIsLoading(false);
      }
    }

    void load();
    return () => { isActive = false; controller.abort(); };
  }, [accessToken, apiConfigError, canManageProject, currentProject.id]);

  const openCreateModal = () => {
    setShowCreateModal(true);
    setCreateUrl('');
    setCreateEvents([]);
    setCreateError(null);
  };

  const closeCreateModal = () => {
    if (isCreating) return;
    setShowCreateModal(false);
    setCreateUrl('');
    setCreateEvents([]);
    setCreateError(null);
  };

  const toggleEvent = (event: string) => {
    setCreateEvents((current) =>
      current.includes(event) ? current.filter((e) => e !== event) : [...current, event]
    );
  };

  const handleCreate = async () => {
    const url = createUrl.trim();
    if (!url) { setCreateError('URL is required.'); return; }
    if (!url.startsWith('https://') && !url.startsWith('http://')) {
      setCreateError('URL must start with http:// or https://');
      return;
    }
    if (createEvents.length === 0) { setCreateError('Select at least one event.'); return; }
    setIsCreating(true);
    setCreateError(null);
    try {
      const webhook = await createWebhook(currentProject.id, accessToken!, { url, events: createEvents });
      setWebhooks((current) => [...current, webhook]);
      setShowCreateModal(false);
    } catch (err) {
      setCreateError((err as Error).message || 'Failed to create webhook.');
    } finally {
      setIsCreating(false);
    }
  };

  const handleDelete = async () => {
    if (!webhookPendingDelete) return;
    setIsDeleting(true);
    try {
      await deleteWebhook(currentProject.id, webhookPendingDelete.id, accessToken!);
      setWebhooks((current) => current.filter((w) => w.id !== webhookPendingDelete.id));
      setWebhookPendingDelete(null);
    } catch (err) {
      setError((err as Error).message || 'Failed to delete webhook.');
    } finally {
      setIsDeleting(false);
    }
  };

  const copySecret = (webhook: Webhook) => {
    void navigator.clipboard.writeText(webhook.signing_secret).then(() => {
      setCopiedId(webhook.id);
      setTimeout(() => setCopiedId(null), 2000);
    });
  };

  return (
    <div className="webhooks-page animate-in">
      <div className="page-header">
        <div>
          <h1 className="page-heading">Webhooks</h1>
          <p className="page-subtitle">
            Receive HTTP POST notifications when events happen in this project.
          </p>
        </div>
        <div className="page-header-actions">
          <button
            className="btn btn-primary"
            onClick={openCreateModal}
            disabled={!canManageProject}
          >
            <Plus size={14} />
            Add Webhook
          </button>
        </div>
      </div>

      {error && (
        <div className="auth-status auth-status-error" role="alert">
          <span>{error}</span>
        </div>
      )}

      {!canManageProject && (
        <p className="env-note">Only owners can manage webhooks for this project.</p>
      )}

      {isLoading ? (
        <DashboardLoader compact title="Loading webhooks" description="Fetching webhook configurations." />
      ) : webhooks.length === 0 ? (
        <div className="empty-state">
          <WebhookIcon size={32} />
          <h3>No webhooks yet</h3>
          <p>Add a webhook to receive HTTP notifications when secrets or team events occur.</p>
          {canManageProject && (
            <button className="btn btn-primary" onClick={openCreateModal}>
              <Plus size={14} />
              Add Webhook
            </button>
          )}
        </div>
      ) : (
        <div className="card">
          <table className="table">
            <thead>
              <tr>
                <th>URL</th>
                <th>Events</th>
                <th>Signing Secret</th>
                <th>Created</th>
                {canManageProject && <th />}
              </tr>
            </thead>
            <tbody>
              {webhooks.map((webhook) => (
                <tr key={webhook.id}>
                  <td className="mono" style={{ wordBreak: 'break-all', maxWidth: '280px' }}>
                    {webhook.url}
                  </td>
                  <td>
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px' }}>
                      {webhook.events.map((event) => (
                        <span key={event} className="badge badge-neutral">
                          {EVENT_LABELS[event] ?? event}
                        </span>
                      ))}
                    </div>
                  </td>
                  <td>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                      <span className="mono" style={{ fontSize: '11px', opacity: 0.6 }}>
                        {webhook.signing_secret.slice(0, 8)}••••••••
                      </span>
                      <button
                        className="btn btn-ghost btn-icon-sm"
                        title="Copy signing secret"
                        onClick={() => copySecret(webhook)}
                      >
                        {copiedId === webhook.id ? <Check size={13} /> : <Copy size={13} />}
                      </button>
                    </div>
                  </td>
                  <td style={{ whiteSpace: 'nowrap' }}>{formatDate(webhook.created_at)}</td>
                  {canManageProject && (
                    <td>
                      <button
                        className="btn btn-ghost btn-icon-sm btn-danger-ghost"
                        title="Delete webhook"
                        onClick={() => setWebhookPendingDelete(webhook)}
                      >
                        <Trash2 size={14} />
                      </button>
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Create Modal */}
      <Modal
        isOpen={showCreateModal}
        onClose={closeCreateModal}
        title="Add Webhook"
        initialFocusRef={urlInputRef}
        footer={
          <>
            <button className="btn btn-secondary" onClick={closeCreateModal} disabled={isCreating}>
              Cancel
            </button>
            <button className="btn btn-primary" onClick={handleCreate} disabled={isCreating}>
              <Plus size={14} />
              {isCreating ? 'Adding...' : 'Add Webhook'}
            </button>
          </>
        }
      >
        <div className="form-group">
          <label htmlFor="webhook-url-input">Endpoint URL</label>
          <input
            id="webhook-url-input"
            ref={urlInputRef}
            className="input mono"
            placeholder="https://example.com/hooks/envbasis"
            value={createUrl}
            onChange={(e) => setCreateUrl(e.target.value)}
            disabled={isCreating}
          />
        </div>
        <div className="form-group" style={{ marginBottom: 0 }}>
          <label>Events</label>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', marginTop: '6px' }}>
            {supportedEvents.map((event) => (
              <label key={event} style={{ display: 'flex', alignItems: 'center', gap: '8px', cursor: 'pointer', fontSize: '13px' }}>
                <input
                  type="checkbox"
                  checked={createEvents.includes(event)}
                  onChange={() => toggleEvent(event)}
                  disabled={isCreating}
                />
                <span className="mono">{event}</span>
                <span className="text-secondary" style={{ fontSize: '12px' }}>
                  {EVENT_LABELS[event] ? `— ${EVENT_LABELS[event]}` : ''}
                </span>
              </label>
            ))}
          </div>
        </div>
        {createError && <p className="env-form-error" role="alert" style={{ marginTop: '12px' }}>{createError}</p>}
      </Modal>

      {/* Delete Confirm */}
      <ConfirmDialog
        isOpen={Boolean(webhookPendingDelete)}
        title="Delete Webhook"
        description={
          webhookPendingDelete
            ? `Delete the webhook for "${webhookPendingDelete.url}"? It will stop receiving events immediately.`
            : ''
        }
        confirmLabel="Delete Webhook"
        onConfirm={() => { void handleDelete(); }}
        onClose={() => { if (!isDeleting) setWebhookPendingDelete(null); }}
        isBusy={isDeleting}
        tone="danger"
      />
    </div>
  );
}
