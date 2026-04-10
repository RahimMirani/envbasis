import type { Project } from '../types/api';

const STORAGE_KEY = 'envbasis.project-discovery.v1';
const MAX_RECENT_PROJECTS = 8;

export type ProjectSortMode = 'recent' | 'name' | 'created';

export interface ProjectDiscoveryState {
  pinnedProjectIds: string[];
  recentProjectIds: string[];
}

const DEFAULT_STATE: ProjectDiscoveryState = {
  pinnedProjectIds: [],
  recentProjectIds: [],
};

function canUseStorage(): boolean {
  return typeof window !== 'undefined' && typeof window.localStorage !== 'undefined';
}

function uniqueStrings(values: unknown): string[] {
  if (!Array.isArray(values)) {
    return [];
  }

  return [...new Set(values.filter((value): value is string => typeof value === 'string'))];
}

function sanitizeState(value: unknown): ProjectDiscoveryState {
  if (!value || typeof value !== 'object') {
    return DEFAULT_STATE;
  }

  const candidate = value as Partial<ProjectDiscoveryState>;

  return {
    pinnedProjectIds: uniqueStrings(candidate.pinnedProjectIds),
    recentProjectIds: uniqueStrings(candidate.recentProjectIds).slice(0, MAX_RECENT_PROJECTS),
  };
}

function persistState(state: ProjectDiscoveryState): ProjectDiscoveryState {
  const nextState = sanitizeState(state);

  if (!canUseStorage()) {
    return nextState;
  }

  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(nextState));
  } catch {
    // Ignore storage failures and continue with the in-memory value.
  }

  return nextState;
}

export function getProjectDiscoveryState(): ProjectDiscoveryState {
  if (!canUseStorage()) {
    return DEFAULT_STATE;
  }

  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    return raw ? sanitizeState(JSON.parse(raw)) : DEFAULT_STATE;
  } catch {
    return DEFAULT_STATE;
  }
}

export function markProjectVisited(projectId: string): ProjectDiscoveryState {
  const state = getProjectDiscoveryState();
  return persistState({
    ...state,
    recentProjectIds: [projectId, ...state.recentProjectIds.filter((id) => id !== projectId)].slice(
      0,
      MAX_RECENT_PROJECTS
    ),
  });
}

export function togglePinnedProject(projectId: string): ProjectDiscoveryState {
  const state = getProjectDiscoveryState();
  const isPinned = state.pinnedProjectIds.includes(projectId);

  return persistState({
    ...state,
    pinnedProjectIds: isPinned
      ? state.pinnedProjectIds.filter((id) => id !== projectId)
      : [projectId, ...state.pinnedProjectIds],
  });
}

export function isProjectPinned(projectId: string, state: ProjectDiscoveryState): boolean {
  return state.pinnedProjectIds.includes(projectId);
}

export function isProjectRecent(projectId: string, state: ProjectDiscoveryState): boolean {
  return state.recentProjectIds.includes(projectId);
}

export function matchesProjectSearch(project: Project, query: string): boolean {
  const normalizedQuery = query.trim().toLowerCase();
  if (!normalizedQuery) {
    return true;
  }

  const haystack = `${project.name} ${project.description || ''}`.toLowerCase();
  return haystack.includes(normalizedQuery);
}

function compareDateDesc(left: string | null | undefined, right: string | null | undefined): number {
  const leftTime = left ? new Date(left).getTime() : 0;
  const rightTime = right ? new Date(right).getTime() : 0;
  return rightTime - leftTime;
}

export function sortProjectsForDiscovery(
  projects: Project[],
  state: ProjectDiscoveryState,
  sortMode: ProjectSortMode
): Project[] {
  const recentOrder = new Map(state.recentProjectIds.map((projectId, index) => [projectId, index]));

  return [...projects].sort((left, right) => {
    const leftPinned = Number(isProjectPinned(left.id, state));
    const rightPinned = Number(isProjectPinned(right.id, state));
    if (leftPinned !== rightPinned) {
      return rightPinned - leftPinned;
    }

    if (sortMode === 'recent') {
      const leftRecentIndex = recentOrder.get(left.id) ?? Number.MAX_SAFE_INTEGER;
      const rightRecentIndex = recentOrder.get(right.id) ?? Number.MAX_SAFE_INTEGER;
      if (leftRecentIndex !== rightRecentIndex) {
        return leftRecentIndex - rightRecentIndex;
      }

      const activityDiff = compareDateDesc(
        left.last_activity_at || left.created_at,
        right.last_activity_at || right.created_at
      );
      if (activityDiff !== 0) {
        return activityDiff;
      }
    }

    if (sortMode === 'created') {
      const createdDiff = compareDateDesc(left.created_at, right.created_at);
      if (createdDiff !== 0) {
        return createdDiff;
      }
    }

    if (sortMode === 'name') {
      const nameDiff = left.name.localeCompare(right.name, undefined, { sensitivity: 'base' });
      if (nameDiff !== 0) {
        return nameDiff;
      }
    }

    return left.name.localeCompare(right.name, undefined, { sensitivity: 'base' });
  });
}
