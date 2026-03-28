const REDIRECT_KEY = 'envbasis_redirect_path';

export function getStoredRedirectPath(): string | null {
  try {
    return sessionStorage.getItem(REDIRECT_KEY);
  } catch {
    return null;
  }
}

export function setStoredRedirectPath(path: string): void {
  try {
    sessionStorage.setItem(REDIRECT_KEY, path);
  } catch {
    // Ignore storage errors
  }
}

export function clearStoredRedirectPath(): void {
  try {
    sessionStorage.removeItem(REDIRECT_KEY);
  } catch {
    // Ignore storage errors
  }
}
