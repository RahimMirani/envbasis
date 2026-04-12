import { useCallback, useEffect, useRef, useState } from 'react';
import { Outlet, useNavigate, useParams } from 'react-router-dom';
import TopBar from '../components/TopBar';
import Sidebar from '../components/Sidebar';
import SectionLoader from '../components/SectionLoader';
import { useAuth } from '../auth/useAuth';
import {
  getProject,
  listEnvironments,
  getProjectSecretStats,
  listProjects,
} from '../lib/api';
import { createProjectPageCache } from '../lib/projectPageCache';
import { markProjectVisited } from '../lib/projectDiscovery';
import type { Project, Environment, SecretStats } from '../types/api';

export default function ProjectLayout() {
  const { projectId } = useParams<{ projectId: string }>();
  const navigate = useNavigate();
  const { accessToken, apiConfigError } = useAuth();

  const [currentProject, setCurrentProject] = useState<Project | null>(null);
  const [projects, setProjects] = useState<Project[]>([]);
  const [environments, setEnvironments] = useState<Environment[]>([]);
  const [secretStats, setSecretStats] = useState<SecretStats | null>(null);
  const [isSecretStatsLoading, setIsSecretStatsLoading] = useState(true);
  const [currentEnv, setCurrentEnv] = useState('all');
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const pageCacheRef = useRef(createProjectPageCache());

  const projectBasePath = `/projects/${projectId}`;
  const canManageProject = currentProject?.role === 'owner';

  useEffect(() => {
    pageCacheRef.current.clear();
  }, [projectId]);

  useEffect(() => {
    if (!accessToken || !projectId) {
      return undefined;
    }

    if (apiConfigError) {
      setError(apiConfigError);
      setIsLoading(false);
      return undefined;
    }

    let isActive = true;
    const controller = new AbortController();

    async function loadProjectData() {
      setIsLoading(true);
      setError(null);

      try {
        const [project, envList, projectList] = await Promise.all([
          getProject(projectId!, accessToken!, { signal: controller.signal }),
          listEnvironments(projectId!, accessToken!, { signal: controller.signal }),
          listProjects(accessToken!, { signal: controller.signal }).catch(() => []),
        ]);

        if (!isActive) {
          return;
        }

        setCurrentProject(project);
        setProjects(projectList);
        setEnvironments(envList);
      } catch (loadError) {
        if (!isActive || controller.signal.aborted) {
          return;
        }

        const err = loadError as Error & { status?: number };
        if (err.status === 404 || err.status === 403) {
          navigate('/', { replace: true });
          return;
        }

        setError(err.message || 'Failed to load project.');
      } finally {
        if (isActive) {
          setIsLoading(false);
        }
      }
    }

    void loadProjectData();

    return () => {
      isActive = false;
      controller.abort();
    };
  }, [accessToken, apiConfigError, navigate, projectId]);

  useEffect(() => {
    if (!accessToken || !projectId || apiConfigError) {
      return undefined;
    }

    let isActive = true;
    const controller = new AbortController();

    async function loadSecretStats() {
      setIsSecretStatsLoading(true);

      try {
        const stats = await getProjectSecretStats(projectId!, accessToken!, {
          signal: controller.signal,
        });

        if (isActive) {
          setSecretStats(stats);
        }
      } catch {
        if (isActive) {
          setSecretStats(null);
        }
      } finally {
        if (isActive) {
          setIsSecretStatsLoading(false);
        }
      }
    }

    void loadSecretStats();

    return () => {
      isActive = false;
      controller.abort();
    };
  }, [accessToken, apiConfigError, projectId]);

  useEffect(() => {
    if (currentEnv === 'all') {
      return;
    }

    if (!environments.some((environment) => environment.name === currentEnv)) {
      setCurrentEnv('all');
    }
  }, [currentEnv, environments]);

  useEffect(() => {
    if (!currentProject?.id) {
      return;
    }

    markProjectVisited(currentProject.id);
  }, [currentProject?.id]);

  const refreshSecretStats = useCallback(async () => {
    if (!accessToken || !projectId) {
      return;
    }

    setIsSecretStatsLoading(true);

    try {
      const stats = await getProjectSecretStats(projectId, accessToken);
      setSecretStats(stats);
    } catch {
      setSecretStats(null);
    } finally {
      setIsSecretStatsLoading(false);
    }
  }, [accessToken, projectId]);

  const handleEnvironmentCreated = (environment: Environment) => {
    setEnvironments((current) => [...current, environment]);
    setSecretStats((current) =>
      current
        ? {
            ...current,
            environments: [
              ...current.environments,
              {
                environment_id: environment.id,
                environment_name: environment.name,
                secret_count: 0,
                last_updated_at: null,
                last_activity_at: null,
              },
            ],
          }
        : current
    );
    setCurrentProject((current) =>
      current
        ? { ...current, environment_count: (current.environment_count || 0) + 1 }
        : current
    );
    setProjects((current) =>
      current.map((project) =>
        project.id === environment.project_id
          ? { ...project, environment_count: (project.environment_count || 0) + 1 }
          : project
      )
    );
  };

  const handleEnvironmentUpdated = (updated: Environment) => {
    setEnvironments((current) =>
      current.map((env) => (env.id === updated.id ? updated : env))
    );
    setSecretStats((current) =>
      current
        ? {
            ...current,
            environments: current.environments.map((item) =>
              item.environment_id === updated.id
                ? { ...item, environment_name: updated.name }
                : item
            ),
          }
        : current
    );
  };

  const handleEnvironmentDeleted = (envId: string) => {
    setEnvironments((current) => current.filter((env) => env.id !== envId));
    setSecretStats((current) =>
      current
        ? {
            ...current,
            environments: current.environments.filter((item) => item.environment_id !== envId),
            total_secret_count: current.environments
              .filter((item) => item.environment_id !== envId)
              .reduce((sum, item) => sum + item.secret_count, 0),
          }
        : current
    );
    setCurrentProject((current) =>
      current
        ? { ...current, environment_count: Math.max(0, (current.environment_count || 0) - 1) }
        : current
    );
    setProjects((current) =>
      current.map((project) =>
        project.id === projectId
          ? { ...project, environment_count: Math.max(0, (project.environment_count || 0) - 1) }
          : project
      )
    );
  };

  const handleProjectUpdated = (updated: Project) => {
    setCurrentProject(updated);
    setProjects((current) =>
      current.map((project) => (project.id === updated.id ? updated : project))
    );
  };

  const handleMemberCountChanged = (delta: number) => {
    if (!delta) {
      return;
    }

    setCurrentProject((current) =>
      current
        ? {
            ...current,
            member_count: Math.max(0, (current.member_count || 0) + delta),
          }
        : current
    );
    setProjects((current) =>
      current.map((project) =>
        project.id === projectId
          ? {
              ...project,
              member_count: Math.max(0, (project.member_count || 0) + delta),
            }
          : project
      )
    );
  };

  const handleRuntimeTokenCountChanged = (delta: number) => {
    if (!delta) {
      return;
    }

    setCurrentProject((current) =>
      current
        ? {
            ...current,
            runtime_token_count: Math.max(0, (current.runtime_token_count || 0) + delta),
          }
        : current
    );
    setProjects((current) =>
      current.map((project) =>
        project.id === projectId
          ? {
              ...project,
              runtime_token_count: Math.max(0, (project.runtime_token_count || 0) + delta),
            }
          : project
      )
    );
  };

  if (isLoading) {
    return (
      <div className="project-layout-loading">
        <SectionLoader label="Loading project" />
      </div>
    );
  }

  if (error || !currentProject) {
    return (
      <div className="project-layout-error">
        <h2>Error</h2>
        <p>{error || 'Project not found.'}</p>
        <button className="btn btn-primary" onClick={() => navigate('/')}>
          Back to Projects
        </button>
      </div>
    );
  }

  return (
    <div className="project-layout">
      <TopBar
        projectName={currentProject.name}
        environments={environments}
        currentEnv={currentEnv}
        onEnvChange={setCurrentEnv}
        onMenuOpen={() => setSidebarOpen(true)}
      />
      <div className="project-layout-body">
        <div
          className={`sidebar-backdrop${sidebarOpen ? ' sidebar-open' : ''}`}
          onClick={() => setSidebarOpen(false)}
        />
        <Sidebar
          basePath={projectBasePath}
          projectName={currentProject.name}
          projectRole={currentProject.role}
          canViewAuditLogs={currentProject.can_view_audit_logs}
          currentProjectId={currentProject.id}
          projects={projects}
          open={sidebarOpen}
          onClose={() => setSidebarOpen(false)}
        />
        <main className="project-layout-main">
          <Outlet
            context={{
              currentProject,
              projectBasePath,
              environments,
              currentEnv,
              canManageProject,
              secretStats,
              isSecretStatsLoading,
              pageCache: pageCacheRef.current,
              refreshSecretStats,
              onEnvironmentCreated: handleEnvironmentCreated,
              onEnvironmentUpdated: handleEnvironmentUpdated,
              onEnvironmentDeleted: handleEnvironmentDeleted,
              onProjectUpdated: handleProjectUpdated,
              onMemberCountChanged: handleMemberCountChanged,
              onRuntimeTokenCountChanged: handleRuntimeTokenCountChanged,
            }}
          />
        </main>
      </div>
    </div>
  );
}
