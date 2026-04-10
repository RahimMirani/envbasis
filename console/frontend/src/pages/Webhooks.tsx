import { useEffect, useRef, useState } from 'react';
import {
  Plus,
  Trash2,
  Copy,
  Check,
  Webhook as WebhookIcon,
  Activity,
  Send,
  RefreshCw,
} from 'lucide-react';
import { useOutletContext } from 'react-router-dom';
import ConfirmDialog from '../components/ConfirmDialog';
import SectionLoader from '../components/SectionLoader';
import Modal from '../components/Modal';
import { useAuth } from '../auth/useAuth';
import {
  listWebhooks,
  createWebhook,
  deleteWebhook,
  listWebhookEvents,
  listWebhookDeliveries,
  sendTestWebhook,
  isAbortError,
} from '../lib/api';
import { formatDate, formatRelativeTime } from '../lib/format';
import type { ProjectPageCacheApi } from '../lib/projectPageCache';
import type { Project, Webhook, WebhookDelivery } from '../types/api';

interface OutletContextType {
  currentProject: Project;
  canManageProject: boolean;
  pageCache: ProjectPageCacheApi;
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

interface DeliveryHistoryState {
  webhook: Webhook | null;
  deliveries: WebhookDelivery[];
  isLoading: boolean;
  error: string | null;
}

interface WebhooksCacheEntry {
  supportedEvents: string[];
  webhooks: Webhook[];
}

function getDeliveryBadgeClass(status: string): string {
  if (status === 'success') {
    return 'badge-success';
  }

  if (status === 'http_error') {
    return 'badge-warning';
  }

  return 'badge-danger';
}

function getDeliveryStatusLabel(delivery: WebhookDelivery): string {
  if (delivery.status === 'success') {
    return delivery.response_status ? `Delivered (${delivery.response_status})` : 'Delivered';
  }

  if (delivery.status === 'http_error') {
    return delivery.response_status ? `HTTP ${delivery.response_status}` : 'HTTP error';
  }

  return 'Network error';
}

export default function WebhooksPage() {
  const { currentProject, canManageProject, pageCache } = useOutletContext<OutletContextType>();
  const { accessToken, apiConfigError } = useAuth();
  const webhooksCacheKey = `webhooks:${currentProject.id}`;
  const cachedWebhooksData = pageCache.get<WebhooksCacheEntry>(webhooksCacheKey);

  const [webhooks, setWebhooks] = useState<Webhook[]>(() => cachedWebhooksData?.webhooks ?? []);
  const [supportedEvents, setSupportedEvents] = useState<string[]>(
    () => cachedWebhooksData?.supportedEvents ?? DEFAULT_SUPPORTED_EVENTS
  );
  const [isLoading, setIsLoading] = useState(() => !cachedWebhooksData);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [showCreateModal, setShowCreateModal] = useState(false);
  const [createUrl, setCreateUrl] = useState('');
  const [createEvents, setCreateEvents] = useState<string[]>([]);
  const [createError, setCreateError] = useState<string | null>(null);
  const [isCreating, setIsCreating] = useState(false);
  const urlInputRef = useRef<HTMLInputElement>(null);

  const [webhookPendingDelete, setWebhookPendingDelete] = useState<Webhook | null>(null);
  const [isDeleting, setIsDeleting] = useState(false);

  const [historyState, setHistoryState] = useState<DeliveryHistoryState>({
    webhook: null,
    deliveries: [],
    isLoading: false,
    error: null,
  });
  const [testingWebhookId, setTestingWebhookId] = useState<string | null>(null);
  const [copiedId, setCopiedId] = useState<string | null>(null);

  const loadWebhooksData = async (showSpinner = false, signal?: AbortSignal) => {
    if (!accessToken) {
      return;
    }

    if (apiConfigError) {
      setError(apiConfigError);
      setIsLoading(false);
      setIsRefreshing(false);
      return;
    }

    if (!canManageProject) {
      setWebhooks([]);
      setSupportedEvents(DEFAULT_SUPPORTED_EVENTS);
      setError(null);
      setIsLoading(false);
      setIsRefreshing(false);
      return;
    }

    if (cachedWebhooksData && !showSpinner) {
      setIsLoading(false);
      setIsRefreshing(false);
      return;
    }

    if (showSpinner) {
      setIsRefreshing(true);
    } else {
      setIsLoading(true);
    }
    setError(null);

    try {
      const [webhooksResult, eventsResult] = await Promise.allSettled([
        listWebhooks(currentProject.id, accessToken, { signal }),
        listWebhookEvents(currentProject.id, accessToken, { signal }),
      ]);

      if (signal?.aborted) {
        return;
      }

      if (webhooksResult.status === 'rejected') {
        throw webhooksResult.reason;
      }

      setWebhooks(webhooksResult.value);
      setSupportedEvents(
        eventsResult.status === 'fulfilled' ? eventsResult.value : DEFAULT_SUPPORTED_EVENTS
      );
      pageCache.set<WebhooksCacheEntry>(webhooksCacheKey, {
        webhooks: webhooksResult.value,
        supportedEvents:
          eventsResult.status === 'fulfilled' ? eventsResult.value : DEFAULT_SUPPORTED_EVENTS,
      });
    } catch (loadError) {
      if (signal?.aborted || isAbortError(loadError)) {
        return;
      }

      setError((loadError as Error).message || 'Failed to load webhooks.');
    } finally {
      if (signal?.aborted) {
        return;
      }

      setIsLoading(false);
      setIsRefreshing(false);
    }
  };

  useEffect(() => {
    const controller = new AbortController();
    void loadWebhooksData(false, controller.signal);

    return () => {
      controller.abort();
    };
  }, [accessToken, apiConfigError, cachedWebhooksData, canManageProject, currentProject.id]);

  useEffect(() => {
    if (!isLoading && !error) {
      pageCache.set<WebhooksCacheEntry>(webhooksCacheKey, {
        webhooks,
        supportedEvents,
      });
    }
  }, [error, isLoading, pageCache, supportedEvents, webhooks, webhooksCacheKey]);

  const openCreateModal = () => {
    setShowCreateModal(true);
    setCreateUrl('');
    setCreateEvents([]);
    setCreateError(null);
  };

  const closeCreateModal = () => {
    if (isCreating) {
      return;
    }
    setShowCreateModal(false);
    setCreateUrl('');
    setCreateEvents([]);
    setCreateError(null);
  };

  const closeHistoryModal = () => {
    if (testingWebhookId) {
      return;
    }

    setHistoryState({
      webhook: null,
      deliveries: [],
      isLoading: false,
      error: null,
    });
  };

  const toggleEvent = (event: string) => {
    setCreateEvents((current) =>
      current.includes(event) ? current.filter((value) => value !== event) : [...current, event]
    );
  };

  const handleCreate = async () => {
    const url = createUrl.trim();
    if (!url) {
      setCreateError('URL is required.');
      return;
    }
    if (!url.startsWith('https://') && !url.startsWith('http://')) {
      setCreateError('URL must start with http:// or https://');
      return;
    }
    if (createEvents.length === 0) {
      setCreateError('Select at least one event.');
      return;
    }

    setIsCreating(true);
    setCreateError(null);

    try {
      const webhook = await createWebhook(currentProject.id, accessToken!, {
        url,
        events: createEvents,
      });
      setWebhooks((current) => [...current, webhook]);
      setShowCreateModal(false);
    } catch (createErrorValue) {
      setCreateError((createErrorValue as Error).message || 'Failed to create webhook.');
    } finally {
      setIsCreating(false);
    }
  };

  const handleDelete = async () => {
    if (!webhookPendingDelete) {
      return;
    }

    setIsDeleting(true);

    try {
      await deleteWebhook(currentProject.id, webhookPendingDelete.id, accessToken!);
      setWebhooks((current) => current.filter((webhook) => webhook.id !== webhookPendingDelete.id));
      if (historyState.webhook?.id === webhookPendingDelete.id) {
        closeHistoryModal();
      }
      setWebhookPendingDelete(null);
    } catch (deleteErrorValue) {
      setError((deleteErrorValue as Error).message || 'Failed to delete webhook.');
    } finally {
      setIsDeleting(false);
    }
  };

  const handleCopySecret = (webhook: Webhook) => {
    void navigator.clipboard.writeText(webhook.signing_secret).then(() => {
      setCopiedId(webhook.id);
      setTimeout(() => setCopiedId(null), 2000);
    });
  };

  const handleOpenHistory = async (webhook: Webhook) => {
    setHistoryState({
      webhook,
      deliveries: [],
      isLoading: true,
      error: null,
    });

    try {
      const deliveries = await listWebhookDeliveries(currentProject.id, webhook.id, accessToken!, {
        limit: 12,
      });
      setHistoryState({
        webhook,
        deliveries,
        isLoading: false,
        error: null,
      });
    } catch (historyError) {
      setHistoryState({
        webhook,
        deliveries: [],
        isLoading: false,
        error: (historyError as Error).message || 'Failed to load webhook activity.',
      });
    }
  };

  const handleSendTest = async (webhook: Webhook) => {
    setTestingWebhookId(webhook.id);
    setError(null);

    try {
      const delivery = await sendTestWebhook(currentProject.id, webhook.id, accessToken!);
      setWebhooks((current) =>
        current.map((item) =>
          item.id === webhook.id ? { ...item, latest_delivery: delivery } : item
        )
      );

      if (historyState.webhook?.id === webhook.id) {
        setHistoryState((current) => ({
          ...current,
          deliveries: [delivery, ...current.deliveries].slice(0, 12),
          error: null,
        }));
      }
    } catch (testErrorValue) {
      const nextError = (testErrorValue as Error).message || 'Failed to send test webhook.';
      setError(nextError);
      if (historyState.webhook?.id === webhook.id) {
        setHistoryState((current) => ({
          ...current,
          error: nextError,
        }));
      }
    } finally {
      setTestingWebhookId(null);
    }
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
            className="btn btn-secondary"
            onClick={() => {
              void loadWebhooksData(true);
            }}
            disabled={!canManageProject || isRefreshing || isLoading}
          >
            <RefreshCw size={14} className={isRefreshing ? 'icon-spin' : ''} />
            {isRefreshing ? 'Refreshing...' : 'Refresh Status'}
          </button>
          <button className="btn btn-primary" onClick={openCreateModal} disabled={!canManageProject}>
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
        <SectionLoader label="Loading webhooks" />
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
          <div className="table-wrapper">
            <table className="table">
              <thead>
                <tr>
                  <th>URL</th>
                  <th>Events</th>
                  <th>Last Delivery</th>
                  <th>Signing Secret</th>
                  <th>Created</th>
                  {canManageProject && <th style={{ width: 260 }}>Actions</th>}
                </tr>
              </thead>
              <tbody>
                {webhooks.map((webhook) => {
                  const latestDelivery = webhook.latest_delivery;
                  const isTesting = testingWebhookId === webhook.id;

                  return (
                    <tr key={webhook.id}>
                      <td className="mono" style={{ wordBreak: 'break-all', maxWidth: '260px' }}>
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
                        {latestDelivery ? (
                          <div className="webhook-delivery-summary">
                            <span className={`badge ${getDeliveryBadgeClass(latestDelivery.status)}`}>
                              {getDeliveryStatusLabel(latestDelivery)}
                            </span>
                            <span className="webhook-delivery-time">
                              {formatRelativeTime(latestDelivery.created_at)}
                            </span>
                          </div>
                        ) : (
                          <span className="text-secondary">No deliveries yet</span>
                        )}
                      </td>
                      <td>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                          <span className="mono" style={{ fontSize: '11px', opacity: 0.6 }}>
                            {webhook.signing_secret.slice(0, 8)}••••••••
                          </span>
                          <button
                            className="btn btn-ghost btn-icon-sm"
                            title="Copy signing secret"
                            onClick={() => handleCopySecret(webhook)}
                          >
                            {copiedId === webhook.id ? <Check size={13} /> : <Copy size={13} />}
                          </button>
                        </div>
                      </td>
                      <td style={{ whiteSpace: 'nowrap' }}>{formatDate(webhook.created_at)}</td>
                      {canManageProject && (
                        <td>
                          <div className="webhook-actions">
                            <button
                              className="btn btn-ghost btn-sm"
                              onClick={() => {
                                void handleOpenHistory(webhook);
                              }}
                            >
                              <Activity size={12} />
                              Activity
                            </button>
                            <button
                              className="btn btn-ghost btn-sm"
                              onClick={() => {
                                void handleSendTest(webhook);
                              }}
                              disabled={isTesting}
                            >
                              <Send size={12} />
                              {isTesting ? 'Testing...' : 'Send Test'}
                            </button>
                            <button
                              className="btn btn-ghost btn-icon-sm btn-danger-ghost"
                              title="Delete webhook"
                              onClick={() => setWebhookPendingDelete(webhook)}
                            >
                              <Trash2 size={14} />
                            </button>
                          </div>
                        </td>
                      )}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

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
            onChange={(event) => setCreateUrl(event.target.value)}
            disabled={isCreating}
          />
        </div>
        <div className="form-group">
          <label>Events</label>
          <div className="webhook-event-list">
            {supportedEvents.map((event) => (
              <label key={event} className="webhook-event-item">
                <input
                  type="checkbox"
                  checked={createEvents.includes(event)}
                  onChange={() => toggleEvent(event)}
                  disabled={isCreating}
                />
                <span className="mono">{event}</span>
                <span className="text-secondary" style={{ fontSize: '12px' }}>
                  {EVENT_LABELS[event] ? `- ${EVENT_LABELS[event]}` : ''}
                </span>
              </label>
            ))}
          </div>
        </div>
        <div className="webhook-helper-note">
          Save the webhook, then use <strong>Send Test</strong> to confirm the endpoint is reachable
          and signed correctly.
        </div>
        {createError && (
          <p className="env-form-error" role="alert" style={{ marginTop: '12px' }}>
            {createError}
          </p>
        )}
      </Modal>

      <Modal
        isOpen={Boolean(historyState.webhook)}
        onClose={closeHistoryModal}
        title={historyState.webhook ? `Activity: ${historyState.webhook.url}` : 'Webhook Activity'}
        footer={
          <>
            {historyState.webhook && (
              <button
                className="btn btn-secondary"
                onClick={() => {
                  if (historyState.webhook) {
                    void handleSendTest(historyState.webhook);
                  }
                }}
                disabled={Boolean(testingWebhookId)}
              >
                <Send size={14} />
                {testingWebhookId === historyState.webhook?.id ? 'Testing...' : 'Send Test'}
              </button>
            )}
            <button className="btn btn-primary" onClick={closeHistoryModal} disabled={Boolean(testingWebhookId)}>
              Done
            </button>
          </>
        }
      >
        {historyState.error && (
          <div className="auth-status auth-status-error" role="alert" style={{ marginBottom: '12px' }}>
            <span>{historyState.error}</span>
          </div>
        )}

        {historyState.isLoading ? (
          <SectionLoader label="Loading activity" />
        ) : historyState.deliveries.length === 0 ? (
          <div className="empty-state" style={{ padding: '2rem 1rem' }}>
            <h3>No delivery attempts yet</h3>
            <p>Send a test delivery to confirm this webhook is reachable.</p>
          </div>
        ) : (
          <div className="webhook-delivery-list">
            {historyState.deliveries.map((delivery) => (
              <div className="webhook-delivery-item" key={delivery.id}>
                <div className="webhook-delivery-topline">
                  <span className={`badge ${getDeliveryBadgeClass(delivery.status)}`}>
                    {getDeliveryStatusLabel(delivery)}
                  </span>
                  <span className="webhook-delivery-type">
                    {delivery.delivery_type === 'test' ? 'Manual test' : delivery.event}
                  </span>
                  <span className="webhook-delivery-time">
                    {formatRelativeTime(delivery.created_at)}
                  </span>
                </div>
                <div className="webhook-delivery-meta">
                  <span className="mono">{delivery.event}</span>
                  <span>{formatDate(delivery.created_at)}</span>
                </div>
                {delivery.error_message && (
                  <div className="webhook-delivery-error">{delivery.error_message}</div>
                )}
              </div>
            ))}
          </div>
        )}
      </Modal>

      <ConfirmDialog
        isOpen={Boolean(webhookPendingDelete)}
        title="Delete Webhook"
        description={
          webhookPendingDelete
            ? `Delete the webhook for "${webhookPendingDelete.url}"? It will stop receiving events immediately.`
            : ''
        }
        confirmLabel="Delete Webhook"
        onConfirm={() => {
          void handleDelete();
        }}
        onClose={() => {
          if (!isDeleting) {
            setWebhookPendingDelete(null);
          }
        }}
        isBusy={isDeleting}
        tone="danger"
      />
    </div>
  );
}
