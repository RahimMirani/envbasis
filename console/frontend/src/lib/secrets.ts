import type { Environment } from '../types/api';

export function getDefaultEnvironmentId(
  currentEnv: string,
  environments: Environment[]
): string {
  if (currentEnv === 'all') {
    return environments[0]?.id || '';
  }

  const matchedEnv = environments.find(
    (environment) => environment.name === currentEnv
  );

  return matchedEnv?.id || environments[0]?.id || '';
}
