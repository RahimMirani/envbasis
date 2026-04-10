export interface ProjectPageCacheApi {
  clear(): void;
  delete(key: string): void;
  get<T>(key: string): T | undefined;
  set<T>(key: string, value: T): void;
}

export function createProjectPageCache(): ProjectPageCacheApi {
  const store = new Map<string, unknown>();

  return {
    clear() {
      store.clear();
    },
    delete(key: string) {
      store.delete(key);
    },
    get<T>(key: string) {
      return store.get(key) as T | undefined;
    },
    set<T>(key: string, value: T) {
      store.set(key, value);
    },
  };
}
