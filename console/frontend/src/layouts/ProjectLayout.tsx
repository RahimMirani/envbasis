import { useCallback, useEffect, useState } from 'react';
import { Outlet, useNavigate, useParams } from 'react-router-dom';
import TopBar from '../components/TopBar';
import Sidebar from '../components/Sidebar';
import DashboardLoader from '../components/DashboardLoader';
import { useAuth } from '../auth/useAuth';
import { getProject, listEnvironments, getProjectSecretStats } from '../lib/api';
import type { Project, Environment, SecretStats } from '../types/api';

export default function ProjectLayout() {
  const { projectId } = useParams<{ projectId: string }>();
  const navigate = useNavigate();
  const { accessToken, apiConfigError } = useAuth();

  const [currentProject, setCurrentProject] = useState<Project | null>(null);
  const [environments, setEnvironments] = useState<Environment[]>([]);
  const [secretStats, setSecretStats] = useState<SecretStats | null>(null);
  const [isSecretStatsLoading, setIsSecretStatsLoading] = useState(true);
  const [currentEnv, setCurrentEnv] = useState('all');
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const projectBasePath = `/projects/${projectId}`;
  const canManageProject = currentProject?.role === 'owner';

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
        const [project, envList] = await Promise.all([
          getProject(projectId!, accessToken!, { signal: controller.signal }),
          listEnvironments(projectId!, accessToken!, { signal: controller.signal }),
        ]);

        if (!isActive) {
          return;
        }

        setCurrentProject(project);
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
    if (currentProject) {
      setCurrentProject({
        ...currentProject,
        environment_count: (currentProject.environment_count || 0) + 1,
      });
    }
  };

  const handleProjectUpdated = (updated: Project) => {
    setCurrentProject(updated);
  };

  if (isLoading) {
    return <DashboardLoader title="Loading project" description="Fetching project details." />;
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
      />
      <div className="project-layout-body">
        <Sidebar basePath={projectBasePath} isOwner={currentProject.role === 'owner'} />
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
              refreshSecretStats,
              onEnvironmentCreated: handleEnvironmentCreated,
              onProjectUpdated: handleProjectUpdated,
            }}
          />
        </main>
      </div>
    </div>
  );
}
