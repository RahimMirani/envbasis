import { useEffect, useMemo, useRef, useState, ChangeEvent } from 'react';
import {
  Plus,
  Search,
  Eye,
  EyeOff,
  Copy,
  Pencil,
  Trash2,
  Upload,
  Download,
  Check,
  AlertTriangle,
  History,
  RotateCcw,
} from 'lucide-react';
import { useOutletContext } from 'react-router-dom';
import Checkbox from '../components/Checkbox';
import CodeBlock from '../components/CodeBlock';
import ConfirmDialog from '../components/ConfirmDialog';
import SectionLoader from '../components/SectionLoader';
import Modal from '../components/Modal';
import Select, { envDotClass } from '../components/Select';
import { useAuth } from '../auth/useAuth';
import {
  bulkDeleteSecrets,
  createSecret,
  deleteSecret,
  isAbortError,
  listProjectSecrets,
  pullSecrets,
  pushSecrets,
  revealSecret,
  updateSecret,
  listProjectSecretTags,
  createProjectSecretTag,
  listSecretVersions,
  revealSecretVersion,
  rollbackSecretVersion,
  ApiError,
} from '../lib/api';
import { parseDotenv, serializeDotenv } from '../lib/dotenv';
import { formatDate, formatRelativeTime } from '../lib/format';
import type { ProjectPageCacheApi } from '../lib/projectPageCache';
import { getDefaultEnvironmentId } from '../lib/secrets';
import type { Project, Environment, Secret, ProjectSecret, ProjectSecretTag, SecretVersionItem } from '../types/api';

interface OutletContextType {
  currentEnv: string;
  currentProject: Project;
  environments: Environment[];
  pageCache: ProjectPageCacheApi;
  refreshSecretStats: () => Promise<void>;
}

interface SecretWithEnv extends Secret {
  environment: string;
  environment_id: string;
}

interface RevealedSecretState {
  value: string;
  version: number;
}

interface CopiedSecretState {
  secretId: string;
  version: number;
}

interface SecretsQueryCacheEntry {
  secrets: SecretWithEnv[];
  nextCursor: string | null;
  cachedAt: number;
}

interface UploadResult {
  environmentName: string;
  changed: number;
  unchanged: number;
  duplicateKeys: string[];
  totalKeys: number;
}

interface ExportResult {
  environmentName: string;
  totalKeys: number;
}

const SECRET_PAGE_SIZE = 100;
const SECRET_CACHE_TTL_MS = 30_000;

function buildSecretId(secret: SecretWithEnv): string {
  return `${secret.environment_id}:${secret.path}:${secret.key}`;
}

function buildSecretsQueryKey(
  projectId: string,
  environmentIds: string[],
  key: string,
  tags: string[] = []
): string {
  return `${projectId}::${environmentIds.join(',')}::${key}::${tags.slice().sort().join(',')}`;
}

function mapProjectSecret(secret: ProjectSecret): SecretWithEnv {
  return {
    ...secret,
    environment: secret.environment_name,
  };
}

function mergeSecretPages(
  currentSecrets: SecretWithEnv[],
  nextSecrets: SecretWithEnv[]
): SecretWithEnv[] {
  const byId = new Map<string, SecretWithEnv>();
  [...currentSecrets, ...nextSecrets].forEach((secret) => {
    byId.set(buildSecretId(secret), secret);
  });

  return [...byId.values()].sort((left, right) => {
    const keyComparison = left.key.localeCompare(right.key);
    if (keyComparison !== 0) {
      return keyComparison;
    }

    return left.environment.localeCompare(right.environment);
  });
}

function getEnvironmentBadgeClass(environmentName: string): string {
  return `badge badge-env badge-env-${String(environmentName || '').toLowerCase()}`;
}

function toLocalDateTimeInput(dateString: string | null | undefined): string {
  if (!dateString) {
    return '';
  }

  const date = new Date(dateString);
  if (Number.isNaN(date.getTime())) {
    return '';
  }

  const pad = (value: number) => String(value).padStart(2, '0');
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

function toIsoFromLocalDateTimeInput(value: string): string | null {
  if (!value.trim()) {
    return null;
  }

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return null;
  }

  return date.toISOString();
}

function formatSecretExpiry(expiresAt: string | null): string {
  if (!expiresAt) {
    return 'Never';
  }

  const expiry = new Date(expiresAt);
  if (Number.isNaN(expiry.getTime())) {
    return 'Never';
  }

  if (expiry.getTime() <= Date.now()) {
    return `Expired ${formatDate(expiresAt)}`;
  }

  return formatDate(expiresAt);
}

export default function SecretsPage() {
  const { currentEnv, currentProject, environments, pageCache, refreshSecretStats } =
    useOutletContext<OutletContextType>();
  const { accessToken, apiConfigError } = useAuth();
  const canManageSecrets = currentProject.can_manage_secrets;
  const initialVisibleEnvironments =
    currentEnv === 'all'
      ? environments
      : environments.filter((environment) => environment.name === currentEnv);
  const initialVisibleEnvironmentIds = initialVisibleEnvironments
    .map((environment) => environment.id)
    .sort();
  const secretsPageCacheKey = `secrets:queries:${currentProject.id}`;
  const initialSecretsCache =
    pageCache.get<Map<string, SecretsQueryCacheEntry>>(secretsPageCacheKey) ?? new Map();
  const initialSecretsQueryKey = buildSecretsQueryKey(
    currentProject.id,
    initialVisibleEnvironmentIds,
    ''
  );
  const initialSecretsEntry = initialSecretsCache.get(initialSecretsQueryKey);
  const initialSecretAccessState: 'enabled' | 'checking' | 'disabled' = 'enabled';
  const [search, setSearch] = useState('');
  const [appliedSearch, setAppliedSearch] = useState('');
  const [selectedTags, setSelectedTags] = useState<string[]>([]);
  const [projectTags, setProjectTags] = useState<ProjectSecretTag[]>([]);
  const [secrets, setSecrets] = useState<SecretWithEnv[]>(() => initialSecretsEntry?.secrets ?? []);
  const [nextCursor, setNextCursor] = useState<string | null>(() => initialSecretsEntry?.nextCursor ?? null);
  const [isLoading, setIsLoading] = useState(() => !initialSecretsEntry);
  const [isLoadingMore, setIsLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [secretAccessState, setSecretAccessState] = useState<'enabled' | 'checking' | 'disabled'>(
    initialSecretAccessState
  );
  const [revealedValues, setRevealedValues] = useState<Record<string, RevealedSecretState>>({});
  const [copiedSecret, setCopiedSecret] = useState<CopiedSecretState | null>(null);
  const [showSecretModal, setShowSecretModal] = useState(false);
  const [showUploadModal, setShowUploadModal] = useState(false);
  const [showExportModal, setShowExportModal] = useState(false);
  const [modalMode, setModalMode] = useState<'create' | 'edit'>('create');
  const [secretKey, setSecretKey] = useState('');
  const [secretValue, setSecretValue] = useState('');
  const [secretExpiresAt, setSecretExpiresAt] = useState('');
  const [secretPath, setSecretPath] = useState('/');
  const [secretTags, setSecretTags] = useState('');
  const [secretDescription, setSecretDescription] = useState('');
  const [secretEnvironmentId, setSecretEnvironmentId] = useState('');
  const [uploadEnvironmentId, setUploadEnvironmentId] = useState('');
  const [uploadContent, setUploadContent] = useState('');
  const [uploadFilename, setUploadFilename] = useState('');
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [uploadResult, setUploadResult] = useState<UploadResult | null>(null);
  const [exportEnvironmentId, setExportEnvironmentId] = useState('');
  const [exportError, setExportError] = useState<string | null>(null);
  const [exportResult, setExportResult] = useState<ExportResult | null>(null);
  const [mutationError, setMutationError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [isExporting, setIsExporting] = useState(false);
  const [activeSecretId, setActiveSecretId] = useState<string | null>(null);
  const [secretPendingDelete, setSecretPendingDelete] = useState<SecretWithEnv | null>(null);
  const [selectedSecretIds, setSelectedSecretIds] = useState<string[]>([]);
  const [showBulkDeleteConfirm, setShowBulkDeleteConfirm] = useState(false);
  const [isBulkDeleting, setIsBulkDeleting] = useState(false);
  const [historySecret, setHistorySecret] = useState<SecretWithEnv | null>(null);
  const [historyVersions, setHistoryVersions] = useState<SecretVersionItem[]>([]);
  const [historicalValues, setHistoricalValues] = useState<Record<number, string>>({});
  const [isHistoryLoading, setIsHistoryLoading] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const secretsCacheRef = useRef<Map<string, SecretsQueryCacheEntry>>(initialSecretsCache);

  const visibleEnvironments = useMemo(() => {
    if (currentEnv === 'all') {
      return environments;
    }

    return environments.filter((environment) => environment.name === currentEnv);
  }, [currentEnv, environments]);

  const visibleEnvironmentIds = useMemo(
    () => visibleEnvironments.map((environment) => environment.id).sort(),
    [visibleEnvironments]
  );
  const secretsQueryKey = useMemo(
    () => buildSecretsQueryKey(
      currentProject.id,
      visibleEnvironmentIds,
      appliedSearch,
      selectedTags
    ),
    [appliedSearch, currentProject.id, selectedTags, visibleEnvironmentIds]
  );
  const isSearchPending = search.trim() !== appliedSearch;

  useEffect(() => {
    pageCache.set(secretsPageCacheKey, secretsCacheRef.current);
  }, [pageCache, secretsPageCacheKey]);

  useEffect(() => {
    const timeoutId = window.setTimeout(() => {
      setAppliedSearch(search.trim());
    }, 250);

    return () => {
      window.clearTimeout(timeoutId);
    };
  }, [search]);

  useEffect(() => {
    setSecretAccessState('enabled');
    setSelectedTags([]);
  }, [currentProject.id]);

  useEffect(() => {
    if (!accessToken || visibleEnvironments.length === 0) {
      setProjectTags([]);
      return undefined;
    }

    let active = true;
    const controller = new AbortController();
    async function loadTags() {
      try {
        const tags = await listProjectSecretTags(currentProject.id, accessToken!, {
          signal: controller.signal,
        });
        if (!active) return;
        setProjectTags(tags);
      } catch (structureError) {
        if (active && !isAbortError(structureError)) {
          setError((structureError as Error).message || 'Failed to load tags.');
        }
      }
    }
    void loadTags();
    return () => {
      active = false;
      controller.abort();
    };
  }, [accessToken, currentProject.id, visibleEnvironments]);

  useEffect(() => {
    if (!accessToken) {
      return undefined;
    }

    if (apiConfigError) {
      setError(apiConfigError);
      setIsLoading(false);
      return undefined;
    }

    if (secretAccessState === 'checking') {
      setIsLoading(true);
      return undefined;
    }

    if (secretAccessState === 'disabled') {
      setSecrets([]);
      setNextCursor(null);
      setError(null);
      setIsLoading(false);
      return undefined;
    }

    if (visibleEnvironments.length === 0) {
      setSecrets([]);
      setNextCursor(null);
      setError(null);
      setIsLoading(false);
      return undefined;
    }

    let isActive = true;
    const controller = new AbortController();
    const cachedEntry = secretsCacheRef.current.get(secretsQueryKey);
    const cacheIsFresh =
      cachedEntry !== undefined && Date.now() - cachedEntry.cachedAt < SECRET_CACHE_TTL_MS;

    if (cachedEntry) {
      setSecrets(cachedEntry.secrets);
      setNextCursor(cachedEntry.nextCursor);
      setIsLoading(false);
    } else if (secrets.length === 0) {
      setIsLoading(true);
    }

    async function loadSecrets() {
      setError(null);

      try {
        if (cacheIsFresh) {
          return;
        }

        const response = await listProjectSecrets(currentProject.id, accessToken!, {
          signal: controller.signal,
          key: appliedSearch || undefined,
          environmentIds: visibleEnvironmentIds,
          limit: SECRET_PAGE_SIZE,
          path: '/',
          recursive: true,
          tags: selectedTags,
        });

        if (!isActive) {
          return;
        }

        const nextSecrets = response.secrets.map(mapProjectSecret);

        setSecrets(nextSecrets);
        setNextCursor(response.next_cursor);
        secretsCacheRef.current.set(secretsQueryKey, {
          secrets: nextSecrets,
          nextCursor: response.next_cursor,
          cachedAt: Date.now(),
        });
        pageCache.set(secretsPageCacheKey, secretsCacheRef.current);
      } catch (loadError) {
        if (!isActive || controller.signal.aborted || isAbortError(loadError)) {
          return;
        }

        const apiError = loadError as ApiError;
        if (apiError.status === 403) {
          setError(null);
          setSecrets([]);
          setNextCursor(null);
        } else {
          setError(apiError.message || 'Failed to load secrets.');
          if (!cachedEntry) {
            setSecrets([]);
            setNextCursor(null);
          }
        }
      } finally {
        if (isActive) {
          setIsLoading(false);
        }
      }
    }

    void loadSecrets();

    return () => {
      isActive = false;
      controller.abort();
    };
  }, [
    accessToken,
    apiConfigError,
    appliedSearch,
    currentProject.id,
    pageCache,
    secretAccessState,
    secrets.length,
    secretsPageCacheKey,
    secretsQueryKey,
    selectedTags,
    visibleEnvironments.length,
    visibleEnvironmentIds,
  ]);

  const filteredSecrets = secrets;
  const filteredSecretIds = useMemo(
    () => filteredSecrets.map((secret) => buildSecretId(secret)),
    [filteredSecrets]
  );
  const selectedSecrets = useMemo(
    () => filteredSecrets.filter((secret) => selectedSecretIds.includes(buildSecretId(secret))),
    [filteredSecrets, selectedSecretIds]
  );
  const allVisibleSelected =
    filteredSecretIds.length > 0 && filteredSecretIds.every((secretId) => selectedSecretIds.includes(secretId));

  const defaultEnvironmentId = getDefaultEnvironmentId(currentEnv, environments);
  const cliEnvironmentName =
    currentEnv === 'all' ? environments[0]?.name || 'dev' : currentEnv;
  const syncVisibleSecretState = (nextSecrets: SecretWithEnv[]) => {
    const visibleVersions = new Map(
      nextSecrets.map((secret) => [buildSecretId(secret), secret.version] as const)
    );

    setRevealedValues((current) => {
      let didChange = false;
      const next = { ...current };

      Object.entries(current).forEach(([secretId, revealed]) => {
        const visibleVersion = visibleVersions.get(secretId);
        if (visibleVersion !== undefined && visibleVersion !== revealed.version) {
          delete next[secretId];
          didChange = true;
        }
      });

      return didChange ? next : current;
    });

    setCopiedSecret((current) => {
      if (!current) {
        return current;
      }

      const visibleVersion = visibleVersions.get(current.secretId);
      if (visibleVersion !== undefined && visibleVersion !== current.version) {
        return null;
      }

      return current;
    });
  };

  useEffect(() => {
    syncVisibleSecretState(secrets);
  }, [secrets]);

  useEffect(() => {
    setSelectedSecretIds((current) => current.filter((secretId) => filteredSecretIds.includes(secretId)));
  }, [filteredSecretIds]);

  const revealSecretValue = async (secret: SecretWithEnv): Promise<string> => {
    const secretId = buildSecretId(secret);
    const cachedValue = revealedValues[secretId];
    if (cachedValue && cachedValue.version === secret.version) {
      return cachedValue.value;
    }

    setActiveSecretId(secretId);
    setError(null);

    try {
      const response = await revealSecret(
        currentProject.id,
        secret.environment_id,
        secret.key,
        accessToken!,
        { path: secret.path }
      );
      setRevealedValues((current) => ({
        ...current,
        [secretId]: {
          value: response.value,
          version: secret.version,
        },
      }));
      return response.value;
    } catch (revealError) {
      setError((revealError as Error).message || 'Failed to reveal secret.');
      throw revealError;
    } finally {
      setActiveSecretId((current) => (current === secretId ? null : current));
    }
  };

  const toggleReveal = async (secret: SecretWithEnv) => {
    const secretId = buildSecretId(secret);
    const currentRevealed = revealedValues[secretId];
    if (currentRevealed && currentRevealed.version === secret.version) {
      clearSecretClientState(secretId);
      if (copiedSecret?.secretId === secretId) {
        setCopiedSecret(null);
      }
      return;
    }

    try {
      await revealSecretValue(secret);
    } catch {
      // The page-level error state is already updated by revealSecretValue.
    }
  };

  const handleCopy = async (secret: SecretWithEnv) => {
    const secretId = buildSecretId(secret);

    try {
      const value =
        revealedValues[secretId]?.version === secret.version
          ? revealedValues[secretId]!.value
          : await revealSecretValue(secret);
      await navigator.clipboard.writeText(value);
      setCopiedSecret({ secretId, version: secret.version });
      window.setTimeout(() => {
        setCopiedSecret((current) =>
          current && current.secretId === secretId && current.version === secret.version
            ? null
            : current
        );
      }, 2000);
    } catch {
      // The page-level error state is already updated by revealSecretValue.
    }
  };

  const openCreateModal = () => {
    setModalMode('create');
    setSecretKey('');
    setSecretValue('');
    setSecretExpiresAt('');
    setSecretPath('/');
    setSecretTags(selectedTags.join(', '));
    setSecretDescription('');
    setSecretEnvironmentId(defaultEnvironmentId);
    setMutationError(null);
    setShowSecretModal(true);
  };

  const handleCreateTag = async () => {
    if (!accessToken) return;
    const value = window.prompt('New project tag');
    if (!value?.trim()) return;
    try {
      const tag = await createProjectSecretTag(currentProject.id, accessToken, { name: value.trim() });
      setProjectTags((current) => [...current.filter((item) => item.id !== tag.id), tag]
        .sort((left, right) => left.name.localeCompare(right.name)));
    } catch (tagError) {
      setError((tagError as Error).message || 'Failed to create tag.');
    }
  };

  const openHistory = async (secret: SecretWithEnv) => {
    setHistorySecret(secret);
    setHistoryVersions([]);
    setHistoricalValues({});
    setIsHistoryLoading(true);
    try {
      const response = await listSecretVersions(
        currentProject.id,
        secret.environment_id,
        secret.key,
        accessToken!,
        { path: secret.path }
      );
      setHistoryVersions(response.versions);
    } catch (historyError) {
      setError((historyError as Error).message || 'Failed to load secret history.');
      setHistorySecret(null);
    } finally {
      setIsHistoryLoading(false);
    }
  };

  const revealHistoricalValue = async (version: number) => {
    if (!historySecret) return;
    try {
      const response = await revealSecretVersion(
        currentProject.id,
        historySecret.environment_id,
        historySecret.key,
        version,
        accessToken!,
        { path: historySecret.path }
      );
      setHistoricalValues((current) => ({ ...current, [version]: response.value }));
    } catch (historyError) {
      setError((historyError as Error).message || 'Failed to reveal historical value.');
    }
  };

  const rollbackHistoricalValue = async (version: number) => {
    if (!historySecret || !window.confirm(`Create a new version from v${version}?`)) return;
    try {
      await rollbackSecretVersion(
        currentProject.id,
        historySecret.environment_id,
        historySecret.key,
        version,
        accessToken!,
        { path: historySecret.path }
      );
      invalidateProjectSecretsCache();
      await reloadSecrets();
      setHistorySecret(null);
    } catch (historyError) {
      setError((historyError as Error).message || 'Failed to roll back secret version.');
    }
  };

  const openUploadModal = () => {
    setUploadEnvironmentId(defaultEnvironmentId);
    setUploadContent('');
    setUploadFilename('');
    setUploadError(null);
    setShowUploadModal(true);
    if (fileInputRef.current) {
      fileInputRef.current.value = '';
    }
  };

  const openExportModal = () => {
    setExportEnvironmentId(defaultEnvironmentId);
    setExportError(null);
    setShowExportModal(true);
  };

  const openEditModal = async (secret: SecretWithEnv) => {
    try {
      const value = await revealSecretValue(secret);
      setModalMode('edit');
      setSecretKey(secret.key);
      setSecretValue(value);
      setSecretExpiresAt(toLocalDateTimeInput(secret.expires_at));
      setSecretPath(secret.path);
      setSecretTags(secret.tags.join(', '));
      setSecretDescription(secret.description || '');
      setSecretEnvironmentId(secret.environment_id);
      setMutationError(null);
      setShowSecretModal(true);
    } catch {
      // The page-level error state is already updated by revealSecretValue.
    }
  };

  const closeSecretModal = () => {
    if (isSubmitting) {
      return;
    }

    setShowSecretModal(false);
    setMutationError(null);
  };

  const closeUploadModal = () => {
    if (isUploading) {
      return;
    }

    setShowUploadModal(false);
    setUploadError(null);
    setUploadContent('');
    setUploadFilename('');
    setUploadEnvironmentId(defaultEnvironmentId);
    if (fileInputRef.current) {
      fileInputRef.current.value = '';
    }
  };

  const closeExportModal = () => {
    if (isExporting) {
      return;
    }

    setShowExportModal(false);
    setExportError(null);
  };

  const invalidateProjectSecretsCache = () => {
    const nextCache = new Map(secretsCacheRef.current);

    nextCache.forEach((_value, key) => {
      if (key.startsWith(`${currentProject.id}::`)) {
        nextCache.delete(key);
      }
    });

    secretsCacheRef.current = nextCache;
    pageCache.set(secretsPageCacheKey, secretsCacheRef.current);
  };

  const clearSecretClientState = (secretId: string) => {
    setRevealedValues((current) => {
      if (!(secretId in current)) {
        return current;
      }

      const next = { ...current };
      delete next[secretId];
      return next;
    });
    setCopiedSecret((current) =>
      current && current.secretId === secretId ? null : current
    );
  };

  const clearEnvironmentClientState = (environmentId: string) => {
    setRevealedValues((current) => {
      let didChange = false;
      const next = { ...current };

      Object.keys(current).forEach((secretId) => {
        if (secretId.startsWith(`${environmentId}:`)) {
          delete next[secretId];
          didChange = true;
        }
      });

      return didChange ? next : current;
    });
    setCopiedSecret((current) =>
      current && current.secretId.startsWith(`${environmentId}:`) ? null : current
    );
  };

  const reloadSecrets = async () => {
    if (!accessToken || secretAccessState !== 'enabled' || visibleEnvironments.length === 0) {
      setSecrets([]);
      setNextCursor(null);
      return;
    }

    const response = await listProjectSecrets(currentProject.id, accessToken, {
      key: appliedSearch || undefined,
      environmentIds: visibleEnvironmentIds,
      limit: SECRET_PAGE_SIZE,
      path: '/',
      recursive: true,
      tags: selectedTags,
    });
    const nextSecrets = response.secrets.map(mapProjectSecret);

    setSecrets(nextSecrets);
    setNextCursor(response.next_cursor);
    secretsCacheRef.current.set(secretsQueryKey, {
      secrets: nextSecrets,
      nextCursor: response.next_cursor,
      cachedAt: Date.now(),
    });
    pageCache.set(secretsPageCacheKey, secretsCacheRef.current);
  };

  const handleLoadMore = async () => {
    if (!accessToken || !nextCursor || isLoadingMore || secretAccessState !== 'enabled') {
      return;
    }

    setIsLoadingMore(true);
    setError(null);

    try {
      const response = await listProjectSecrets(currentProject.id, accessToken, {
        key: appliedSearch || undefined,
        environmentIds: visibleEnvironmentIds,
        limit: SECRET_PAGE_SIZE,
        cursor: nextCursor,
        path: '/',
        recursive: true,
        tags: selectedTags,
      });
      const appendedSecrets = response.secrets.map(mapProjectSecret);

      setSecrets((current) => {
        const mergedSecrets = mergeSecretPages(current, appendedSecrets);
        secretsCacheRef.current.set(secretsQueryKey, {
          secrets: mergedSecrets,
          nextCursor: response.next_cursor,
          cachedAt: Date.now(),
        });
        pageCache.set(secretsPageCacheKey, secretsCacheRef.current);
        return mergedSecrets;
      });
      setNextCursor(response.next_cursor);
    } catch (loadError) {
      if (!isAbortError(loadError)) {
        setError((loadError as Error).message || 'Failed to load more secrets.');
      }
    } finally {
      setIsLoadingMore(false);
    }
  };

  const toggleSecretSelection = (secretId: string) => {
    setSelectedSecretIds((current) =>
      current.includes(secretId)
        ? current.filter((id) => id !== secretId)
        : [...current, secretId]
    );
  };

  const toggleSelectAllVisibleSecrets = () => {
    setSelectedSecretIds((current) => {
      if (allVisibleSelected) {
        return current.filter((secretId) => !filteredSecretIds.includes(secretId));
      }

      return [...new Set([...current, ...filteredSecretIds])];
    });
  };

  const handleSaveSecret = async () => {
    const trimmedKey = secretKey.trim().toUpperCase();
    const normalizedTags = [...new Set(
      secretTags.split(',').map((tag) => tag.trim().toLowerCase()).filter(Boolean)
    )];

    if (!secretEnvironmentId) {
      setMutationError('Select an environment.');
      return;
    }

    if (!trimmedKey) {
      setMutationError('Secret key is required.');
      return;
    }

    setIsSubmitting(true);
    setMutationError(null);

    try {
      if (modalMode === 'create') {
        await createSecret(currentProject.id, secretEnvironmentId, accessToken!, {
          key: trimmedKey,
          value: secretValue,
          expires_at: toIsoFromLocalDateTimeInput(secretExpiresAt),
          path: secretPath || '/',
          tags: normalizedTags,
          description: secretDescription.trim() || null,
        });
      } else {
        await updateSecret(
          currentProject.id,
          secretEnvironmentId,
          trimmedKey,
          accessToken!,
          {
            value: secretValue,
            expires_at: toIsoFromLocalDateTimeInput(secretExpiresAt),
            tags: normalizedTags,
            description: secretDescription.trim() || null,
          },
          { path: secretPath }
        );
      }

      if (modalMode === 'edit') {
        clearSecretClientState(`${secretEnvironmentId}:${secretPath}:${trimmedKey}`);
      }
      invalidateProjectSecretsCache();
      await reloadSecrets();
      try {
        await refreshSecretStats();
      } catch {
        // Keep the secret table fresh even if the metadata refresh fails.
      }
      setShowSecretModal(false);
      setMutationError(null);
    } catch (saveError) {
      setMutationError((saveError as Error).message || 'Failed to save secret.');
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleDeleteSecret = async (secret: SecretWithEnv) => {
    const secretId = buildSecretId(secret);
    setActiveSecretId(secretId);
    setError(null);

    try {
      await deleteSecret(currentProject.id, secret.environment_id, secret.key, accessToken!, {
        path: secret.path,
      });
      clearSecretClientState(secretId);
      invalidateProjectSecretsCache();
      await reloadSecrets();
      try {
        await refreshSecretStats();
      } catch {
        // Keep the secret table fresh even if the metadata refresh fails.
      }
    } catch (deleteError) {
      setError((deleteError as Error).message || 'Failed to delete secret.');
    } finally {
      setActiveSecretId(null);
      setSecretPendingDelete(null);
    }
  };

  const handleBulkDeleteSecrets = async () => {
    if (selectedSecrets.length === 0) {
      setShowBulkDeleteConfirm(false);
      return;
    }

    setIsBulkDeleting(true);
    setError(null);

    try {
      await bulkDeleteSecrets(currentProject.id, accessToken!, {
        items: selectedSecrets.map((secret) => ({
          environment_id: secret.environment_id,
          key: secret.key,
          path: secret.path,
        })),
      });
      selectedSecrets.forEach((secret) => {
        clearSecretClientState(buildSecretId(secret));
      });
      setSelectedSecretIds([]);
      setShowBulkDeleteConfirm(false);
      invalidateProjectSecretsCache();
      await reloadSecrets();
      try {
        await refreshSecretStats();
      } catch {
        // Keep the secret table fresh even if the metadata refresh fails.
      }
    } catch (bulkDeleteError) {
      setError((bulkDeleteError as Error).message || 'Failed to delete selected secrets.');
    } finally {
      setIsBulkDeleting(false);
    }
  };

  const handleUploadFileChange = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) {
      return;
    }

    try {
      const text = await file.text();
      setUploadContent(text);
      setUploadFilename(file.name);
      setUploadError(null);
    } catch {
      setUploadError('Failed to read the selected file.');
      setUploadFilename('');
    }
  };

  const handleUploadSecrets = async () => {
    if (!uploadEnvironmentId) {
      setUploadError('Select an environment.');
      return;
    }

    let parsedSecrets: Record<string, string>;
    let duplicateKeys: string[];
    let totalKeys: number;

    try {
      const parsed = parseDotenv(uploadContent);
      parsedSecrets = parsed.secrets;
      duplicateKeys = parsed.duplicateKeys;
      totalKeys = parsed.totalKeys;
    } catch (parseError) {
      setUploadError((parseError as Error).message || 'Failed to parse .env contents.');
      return;
    }

    if (totalKeys === 0) {
      setUploadError('No secrets were found in the provided .env contents.');
      return;
    }

    setIsUploading(true);
    setUploadError(null);

    try {
      const response = await pushSecrets(currentProject.id, uploadEnvironmentId, accessToken!, {
        secrets: parsedSecrets,
        path: '/',
        tags: selectedTags,
      });

      const targetEnvironment = environments.find(
        (environment) => environment.id === uploadEnvironmentId
      );

      clearEnvironmentClientState(uploadEnvironmentId);
      invalidateProjectSecretsCache();
      await reloadSecrets();
      try {
        await refreshSecretStats();
      } catch {
        // Keep the secret table fresh even if the metadata refresh fails.
      }

      setUploadResult({
        environmentName: targetEnvironment?.name || 'selected environment',
        changed: response.changed,
        unchanged: response.unchanged,
        duplicateKeys,
        totalKeys,
      });
      setShowUploadModal(false);
      setUploadContent('');
      setUploadFilename('');
      if (fileInputRef.current) {
        fileInputRef.current.value = '';
      }
    } catch (pushErrorValue) {
      setUploadError((pushErrorValue as Error).message || 'Failed to import .env secrets.');
    } finally {
      setIsUploading(false);
    }
  };

  const handleExportSecrets = async () => {
    if (!exportEnvironmentId) {
      setExportError('Select an environment.');
      return;
    }

    setIsExporting(true);
    setExportError(null);

    try {
      const response = await pullSecrets(currentProject.id, exportEnvironmentId, accessToken!, {
        path: '/',
        recursive: true,
        tags: selectedTags,
      });
      const targetEnvironment = environments.find(
        (environment) => environment.id === exportEnvironmentId
      );
      const environmentName = targetEnvironment?.name || 'environment';
      const dotenvContent = serializeDotenv(response.secrets);
      const blob = new Blob([dotenvContent ? `${dotenvContent}\n` : ''], {
        type: 'text/plain;charset=utf-8',
      });
      const url = window.URL.createObjectURL(blob);
      const anchor = document.createElement('a');
      const safeProjectName =
        currentProject.name.replace(/[^a-z0-9_-]+/gi, '-').replace(/^-+|-+$/g, '') || 'project';
      const safeEnvironmentName =
        environmentName.replace(/[^a-z0-9_-]+/gi, '-').replace(/^-+|-+$/g, '') || 'env';

      anchor.href = url;
      anchor.download = `${safeProjectName}.${safeEnvironmentName}.env`;
      document.body.appendChild(anchor);
      anchor.click();
      document.body.removeChild(anchor);
      window.URL.revokeObjectURL(url);

      setExportResult({
        environmentName,
        totalKeys: Object.keys(response.secrets || {}).length,
      });
      setShowExportModal(false);
    } catch (pullErrorValue) {
      setExportError((pullErrorValue as Error).message || 'Failed to export .env secrets.');
    } finally {
      setIsExporting(false);
    }
  };

  return (
    <div className="secrets-page animate-in">
      <div className="page-header">
        <div>
          <h1 className="page-heading">Secrets</h1>
          <p className="page-subtitle">
            Manage your project's environment variables. Values are hidden by default.
          </p>
        </div>
        <div className="page-header-actions">
          <button
            className="btn btn-danger"
            onClick={() => setShowBulkDeleteConfirm(true)}
            disabled={!canManageSecrets || selectedSecrets.length === 0 || isBulkDeleting}
          >
            <Trash2 size={14} />
            Delete Selected
          </button>
          <button
            className="btn btn-secondary"
            id="bulk-download-btn"
            onClick={openExportModal}
            disabled={environments.length === 0}
          >
            <Download size={14} />
            Download .env
          </button>
          <button
            className="btn btn-secondary"
            id="bulk-upload-btn"
            onClick={openUploadModal}
            disabled={!canManageSecrets || visibleEnvironments.length === 0}
          >
            <Upload size={14} />
            Upload .env
          </button>
          <button
            className="btn btn-primary"
            onClick={openCreateModal}
            id="add-secret-btn"
            disabled={!canManageSecrets || visibleEnvironments.length === 0}
          >
            <Plus size={14} />
            Add Secret
          </button>
        </div>
      </div>

      {!canManageSecrets && (
        <p className="secrets-note">
          You can view and export secrets, but only permitted managers can create, edit, upload,
          or delete them.
        </p>
      )}

      {error && (
        <div className="auth-status auth-status-error" role="alert">
          <span>{error}</span>
        </div>
      )}

      {uploadResult && (
        <div className="secrets-upload-result" role="status">
          <strong>
            {uploadResult.totalKeys} secret{uploadResult.totalKeys !== 1 ? 's' : ''} imported into{' '}
            {uploadResult.environmentName}.
          </strong>
          <span>
            {uploadResult.changed} changed, {uploadResult.unchanged} unchanged.
          </span>
          {uploadResult.duplicateKeys.length > 0 && (
            <span>
              {uploadResult.duplicateKeys.length} duplicate key
              {uploadResult.duplicateKeys.length !== 1 ? 's used' : ' used'} last-value wins.
            </span>
          )}
        </div>
      )}

      {exportResult && (
        <div className="secrets-upload-result" role="status">
          <strong>Downloaded {exportResult.environmentName}.env</strong>
          <span>
            {exportResult.totalKeys} secret{exportResult.totalKeys !== 1 ? 's' : ''} exported.
          </span>
        </div>
      )}

      <div className="secrets-tag-filter">
        <span className="text-secondary text-sm">Tags:</span>
        {projectTags.map((tag) => {
          const selected = selectedTags.includes(tag.name);
          return (
            <button
              key={tag.id}
              className={`badge ${selected ? 'badge-purple' : ''}`}
              onClick={() => setSelectedTags((current) =>
                selected ? current.filter((name) => name !== tag.name) : [...current, tag.name]
              )}
            >
              {tag.name}
            </button>
          );
        })}
        {canManageSecrets && (
          <button className="btn btn-ghost btn-sm" onClick={() => void handleCreateTag()}>
            <Plus size={13} /> Tag
          </button>
        )}
      </div>

      {/* Search */}
      <div className="secrets-toolbar">
        <div className="secrets-search">
          <Search size={14} className="secrets-search-icon" />
          <input
            type="text"
            className="input secrets-search-input"
            placeholder="Search secrets..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            id="secrets-search"
          />
        </div>
        <div className="secrets-toolbar-meta">
          {isSearchPending && <span className="secrets-search-status">Searching…</span>}
          {selectedSecrets.length > 0 && (
            <span className="secrets-selected-count">
              {selectedSecrets.length} selected
            </span>
          )}
          <span className="secrets-count">
            Showing {filteredSecrets.length} secret{filteredSecrets.length !== 1 ? 's' : ''}
            {nextCursor ? '+' : ''}
          </span>
        </div>
      </div>

      {visibleEnvironments.length === 0 ? (
        <div className="empty-state">
          <h3>No environments available</h3>
          <p>Create an environment first before adding secrets.</p>
        </div>
      ) : isLoading ? (
        <SectionLoader label="Loading secrets" />
      ) : filteredSecrets.length === 0 ? (
        <div className="empty-state">
          <h3>No secrets found</h3>
          <p>
            {appliedSearch
              ? 'Try a different search term.'
              : currentEnv === 'all'
                ? 'Add a secret to any environment in this project.'
                : `Add a secret to ${currentEnv}.`}
          </p>
          {canManageSecrets && (
            <button className="btn btn-primary" onClick={openCreateModal}>
              <Plus size={14} />
              Add Secret
            </button>
          )}
        </div>
      ) : (
        <div className="card">
          <div className="table-wrapper">
            <table id="secrets-table">
              <thead>
                <tr>
                  <th style={{ width: 40 }}>
                    <Checkbox
                      checked={allVisibleSelected}
                      indeterminate={selectedSecretIds.length > 0 && !allVisibleSelected}
                      onChange={toggleSelectAllVisibleSecrets}
                      aria-label="Select all visible secrets"
                      disabled={!canManageSecrets || isBulkDeleting}
                    />
                  </th>
                  <th>Key</th>
                  <th>Value</th>
                  <th>Environment</th>
                  <th>Version</th>
                  <th>Expires</th>
                  <th>Updated</th>
                  <th>By</th>
                  <th style={{ width: 140 }}>Actions</th>
                </tr>
              </thead>
              <tbody>
                {filteredSecrets.map((secret) => {
                  const secretId = buildSecretId(secret);
                  const revealedEntry = revealedValues[secretId];
                  const isRevealed = revealedEntry?.version === secret.version;
                  const revealedValue = isRevealed ? revealedEntry.value : undefined;
                  const isCopied =
                    copiedSecret?.secretId === secretId && copiedSecret.version === secret.version;
                  const isBusy = activeSecretId === secretId;
                  return (
                    <tr key={secretId}>
                      <td className="table-checkbox-cell">
                        <Checkbox
                          checked={selectedSecretIds.includes(secretId)}
                          onChange={() => toggleSecretSelection(secretId)}
                          aria-label={`Select secret ${secret.key}`}
                          disabled={!canManageSecrets || isBulkDeleting}
                        />
                      </td>
                      <td>
                        <code className="secret-key">{secret.key}</code>
                        {secret.is_reference && <span className="badge badge-env">Reference</span>}
                        {secret.path !== '/' && (
                          <div className="secret-path-label">{secret.path}</div>
                        )}
                        {secret.tags.length > 0 && (
                          <div className="secret-tag-list">
                            {secret.tags.map((tag) => <span key={tag} className="badge">{tag}</span>)}
                          </div>
                        )}
                      </td>
                      <td>
                        <span
                          className={`secret-value mono ${isRevealed ? 'secret-value-revealed' : ''}`}
                        >
                          {isRevealed ? revealedValue : '••••••••••••'}
                        </span>
                      </td>
                      <td>
                        <span className={getEnvironmentBadgeClass(secret.environment)}>
                          {secret.environment}
                        </span>
                      </td>
                      <td className="text-mono text-sm">v{secret.version}</td>
                      <td className="text-secondary">{formatSecretExpiry(secret.expires_at)}</td>
                      <td className="text-secondary">{formatRelativeTime(secret.updated_at)}</td>
                      <td className="text-secondary">
                        {secret.updated_by_email || 'Unknown user'}
                      </td>
                      <td>
                        <div className="secret-actions">
                          <button
                            className="btn btn-ghost btn-icon btn-sm"
                            onClick={() => void toggleReveal(secret)}
                            data-tooltip={isBusy ? 'Working...' : isRevealed ? 'Hide' : 'Reveal'}
                            aria-label={isRevealed ? 'Hide secret' : 'Reveal secret'}
                            disabled={isBusy}
                          >
                            {isRevealed ? <EyeOff size={14} /> : <Eye size={14} />}
                          </button>
                          <button
                            className="btn btn-ghost btn-icon btn-sm"
                            onClick={() => void handleCopy(secret)}
                            data-tooltip={isCopied ? 'Copied!' : 'Copy'}
                            aria-label="Copy secret value"
                            disabled={isBusy}
                          >
                            {isCopied ? (
                              <Check size={14} className="text-success" />
                            ) : (
                              <Copy size={14} />
                            )}
                          </button>
                          <button
                            className="btn btn-ghost btn-icon btn-sm"
                            onClick={() => void openHistory(secret)}
                            data-tooltip="Version history"
                            aria-label="View version history"
                            disabled={isBusy}
                          >
                            <History size={14} />
                          </button>
                          {canManageSecrets && (
                            <button
                              className="btn btn-ghost btn-icon btn-sm"
                              onClick={() => void openEditModal(secret)}
                              data-tooltip="Edit"
                              aria-label="Edit secret"
                              disabled={isBusy}
                            >
                              <Pencil size={14} />
                            </button>
                          )}
                          {canManageSecrets && (
                            <button
                              className="btn btn-ghost btn-icon btn-sm btn-danger-subtle"
                              onClick={() => setSecretPendingDelete(secret)}
                              data-tooltip="Delete"
                              aria-label="Delete secret"
                              disabled={isBusy}
                            >
                              <Trash2 size={14} />
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
          {nextCursor && (
            <div className="secrets-pagination">
              <span className="secrets-pagination-meta">
                More matching secrets are available.
              </span>
              <button
                className="btn btn-secondary"
                onClick={() => {
                  void handleLoadMore();
                }}
                disabled={isLoadingMore}
              >
                {isLoadingMore ? 'Loading...' : 'Load More'}
              </button>
            </div>
          )}
        </div>
      )}

      {/* CLI Hint */}
      {canManageSecrets && (
        <div className="secrets-cli-hint">
          <CodeBlock
            commands={[
              { cmd: 'envbasis', args: `push --env ${cliEnvironmentName}` },
              { cmd: 'envbasis', args: `pull --env ${cliEnvironmentName}` },
            ]}
          />
        </div>
      )}

      {/* Export Modal */}
      <Modal
        isOpen={showExportModal}
        onClose={closeExportModal}
        title="Download .env"
        footer={
          <>
            <button
              type="button"
              className="btn btn-secondary"
              onClick={closeExportModal}
              disabled={isExporting}
            >
              Cancel
            </button>
            <button
              type="button"
              className="btn btn-primary"
              onClick={handleExportSecrets}
              disabled={isExporting}
            >
              <Download size={14} />
              {isExporting ? 'Downloading...' : 'Download .env'}
            </button>
          </>
        }
      >
        <div className="form-group">
          <label htmlFor="export-secret-env-input">Environment</label>
          <Select
            id="export-secret-env-input"
            value={exportEnvironmentId}
            onChange={setExportEnvironmentId}
            disabled={currentEnv !== 'all' || isExporting}
            placeholder="Select an environment"
            options={environments.map((environment) => ({
              value: environment.id,
              label: environment.name,
              dotClass: envDotClass(environment.name),
            }))}
          />
        </div>
        {exportError && (
          <p className="secrets-form-error" role="alert">
            {exportError}
          </p>
        )}
        <div className="add-secret-warning">
          <AlertTriangle size={14} />
          <span>
            Downloads secret values as a plain-text `.env` file for the selected environment.
          </span>
        </div>
      </Modal>

      {/* Upload Modal */}
      <Modal
        isOpen={showUploadModal}
        onClose={closeUploadModal}
        title="Import .env"
        footer={
          <>
            <button
              type="button"
              className="btn btn-secondary"
              onClick={closeUploadModal}
              disabled={isUploading}
            >
              Cancel
            </button>
            <button
              type="button"
              className="btn btn-primary"
              onClick={handleUploadSecrets}
              disabled={isUploading}
            >
              <Upload size={14} />
              {isUploading ? 'Importing...' : 'Import Secrets'}
            </button>
          </>
        }
      >
        <div className="form-group">
          <label htmlFor="upload-secret-env-input">Environment</label>
          <Select
            id="upload-secret-env-input"
            value={uploadEnvironmentId}
            onChange={setUploadEnvironmentId}
            disabled={currentEnv !== 'all' || isUploading}
            placeholder="Select an environment"
            options={environments.map((environment) => ({
              value: environment.id,
              label: environment.name,
              dotClass: envDotClass(environment.name),
            }))}
          />
        </div>
        <div className="form-group">
          <label htmlFor="upload-dotenv-file-input">Choose .env file</label>
          <input
            ref={fileInputRef}
            id="upload-dotenv-file-input"
            className="input"
            type="file"
            accept=".env,text/plain"
            onChange={(event) => {
              void handleUploadFileChange(event);
            }}
            disabled={isUploading}
          />
          <p className="secrets-upload-hint">
            {uploadFilename
              ? `Loaded ${uploadFilename}. You can still edit the contents below before importing.`
              : 'Upload a .env file or paste its contents below.'}
          </p>
        </div>
        <div className="form-group">
          <label htmlFor="upload-dotenv-content-input">.env contents</label>
          <textarea
            id="upload-dotenv-content-input"
            className="input secrets-upload-textarea mono"
            placeholder={
              'OPENAI_API_KEY=sk-...\nDATABASE_URL=postgres://...\n# Comments are ignored'
            }
            value={uploadContent}
            onChange={(event) => setUploadContent(event.target.value)}
            disabled={isUploading}
            rows={10}
          />
        </div>
        {uploadError && (
          <p className="secrets-form-error" role="alert">
            {uploadError}
          </p>
        )}
        <div className="add-secret-warning">
          <AlertTriangle size={14} />
          <span>Bulk import creates or updates secrets in one environment at a time.</span>
        </div>
      </Modal>

      {/* Secret Modal */}
      <Modal
        isOpen={showSecretModal}
        onClose={closeSecretModal}
        title={modalMode === 'create' ? 'Add Secret' : 'Edit Secret'}
        footer={
          <>
            <button
              type="button"
              className="btn btn-secondary"
              onClick={closeSecretModal}
              disabled={isSubmitting}
            >
              Cancel
            </button>
            <button
              type="button"
              className="btn btn-primary"
              onClick={handleSaveSecret}
              id="save-secret-btn"
              disabled={isSubmitting}
            >
              <Plus size={14} />
              {isSubmitting
                ? modalMode === 'create'
                  ? 'Adding...'
                  : 'Saving...'
                : modalMode === 'create'
                  ? 'Add Secret'
                  : 'Save Secret'}
            </button>
          </>
        }
      >
        <div className="form-group">
          <label htmlFor="secret-key-input">Key name</label>
          <input
            id="secret-key-input"
            name="secret-key-name"
            className="input mono"
            autoComplete="off"
            placeholder="e.g. OPENAI_API_KEY"
            value={secretKey}
            onChange={(e) => setSecretKey(e.target.value.toUpperCase())}
            disabled={modalMode === 'edit' || isSubmitting}
          />
        </div>
        <div className="form-group">
          <label htmlFor="secret-value-input">Value</label>
          <input
            id="secret-value-input"
            name="secret-value"
            className="input mono"
            type="password"
            autoComplete="new-password"
            placeholder="Enter secret value"
            value={secretValue}
            onChange={(e) => setSecretValue(e.target.value)}
            disabled={isSubmitting}
          />
        </div>
        <div className="form-group">
          <label htmlFor="secret-tags-input">Tags</label>
          <input
            id="secret-tags-input"
            className="input"
            value={secretTags}
            onChange={(event) => setSecretTags(event.target.value)}
            disabled={isSubmitting}
            placeholder="critical, database"
          />
        </div>
        <div className="form-group">
          <label htmlFor="secret-description-input">Description</label>
          <textarea
            id="secret-description-input"
            className="input"
            value={secretDescription}
            onChange={(event) => setSecretDescription(event.target.value)}
            disabled={isSubmitting}
            rows={2}
          />
        </div>
        <div className="form-group">
          <label htmlFor="secret-env-input">Environment</label>
          <Select
            id="secret-env-input"
            value={secretEnvironmentId}
            onChange={setSecretEnvironmentId}
            disabled={modalMode === 'edit' || currentEnv !== 'all' || isSubmitting}
            placeholder="Select an environment"
            options={environments.map((environment) => ({
              value: environment.id,
              label: environment.name,
              dotClass: envDotClass(environment.name),
            }))}
          />
        </div>
        <div className="form-group">
          <label htmlFor="secret-expiry-input">Expiration Date</label>
          <input
            id="secret-expiry-input"
            className="input"
            type="datetime-local"
            value={secretExpiresAt}
            onChange={(event) => setSecretExpiresAt(event.target.value)}
            disabled={isSubmitting}
          />
          <p className="secrets-upload-hint">Leave blank for no expiration.</p>
        </div>
        {mutationError && (
          <p className="secrets-form-error" role="alert">
            {mutationError}
          </p>
        )}
        <div className="add-secret-warning">
          <AlertTriangle size={14} />
          <span>Secret values are encrypted at rest and never exposed in logs.</span>
        </div>
      </Modal>
      <Modal
        isOpen={Boolean(historySecret)}
        onClose={() => setHistorySecret(null)}
        title={historySecret ? `History: ${historySecret.key}` : 'Secret History'}
      >
        {historySecret && (
          <p className="text-secondary text-sm mono">{historySecret.environment}:{historySecret.path}</p>
        )}
        {isHistoryLoading ? (
          <SectionLoader label="Loading version history" />
        ) : (
          <div className="secret-history-list">
            {historyVersions.map((version) => (
              <div key={version.version} className="secret-history-row">
                <div className="secret-history-meta">
                  <strong>v{version.version}</strong>
                  <span>{formatDate(version.updated_at)}</span>
                  <span>{version.updated_by_email || 'Unknown user'}</span>
                  {version.archived_at && <span className="badge">Archived</span>}
                  {version.is_deleted && <span className="badge">Deleted</span>}
                </div>
                {historicalValues[version.version] !== undefined && (
                  <code className="secret-history-value">{historicalValues[version.version]}</code>
                )}
                {!version.is_deleted && (
                  <div className="secret-actions">
                    <button
                      className="btn btn-secondary btn-sm"
                      onClick={() => void revealHistoricalValue(version.version)}
                    >
                      <Eye size={13} /> Reveal
                    </button>
                    {canManageSecrets && version.version !== historySecret?.version && (
                      <button
                        className="btn btn-secondary btn-sm"
                        onClick={() => void rollbackHistoricalValue(version.version)}
                      >
                        <RotateCcw size={13} /> Roll Back
                      </button>
                    )}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </Modal>
      <ConfirmDialog
        isOpen={Boolean(secretPendingDelete)}
        title="Delete Secret"
        description={
          secretPendingDelete
            ? `Delete secret "${secretPendingDelete.key}" from ${secretPendingDelete.environment}?`
            : 'Delete this secret?'
        }
        confirmLabel="Delete Secret"
        onConfirm={() => {
          if (secretPendingDelete) {
            void handleDeleteSecret(secretPendingDelete);
          }
        }}
        onClose={() => {
          if (!activeSecretId) {
            setSecretPendingDelete(null);
          }
        }}
        isBusy={Boolean(secretPendingDelete && activeSecretId === buildSecretId(secretPendingDelete))}
      />
      <ConfirmDialog
        isOpen={showBulkDeleteConfirm}
        title="Delete Selected Secrets"
        description={
          selectedSecrets.length > 0
            ? `Delete ${selectedSecrets.length} selected secret${selectedSecrets.length !== 1 ? 's' : ''}?`
            : 'Delete selected secrets?'
        }
        confirmLabel="Delete Selected"
        onConfirm={() => {
          void handleBulkDeleteSecrets();
        }}
        onClose={() => {
          if (!isBulkDeleting) {
            setShowBulkDeleteConfirm(false);
          }
        }}
        isBusy={isBulkDeleting}
      />
    </div>
  );
}
