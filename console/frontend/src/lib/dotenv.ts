export interface ParsedDotenv {
  secrets: Record<string, string>;
  duplicateKeys: string[];
  totalKeys: number;
}

export function parseDotenv(content: string): ParsedDotenv {
  const secrets: Record<string, string> = {};
  const duplicateKeys: string[] = [];
  let totalKeys = 0;

  const lines = content.split('\n');

  for (const rawLine of lines) {
    const line = rawLine.trim();

    if (!line || line.startsWith('#')) {
      continue;
    }

    const equalsIndex = line.indexOf('=');
    if (equalsIndex === -1) {
      continue;
    }

    const key = line.slice(0, equalsIndex).trim();
    let value = line.slice(equalsIndex + 1);

    if (
      (value.startsWith('"') && value.endsWith('"')) ||
      (value.startsWith("'") && value.endsWith("'"))
    ) {
      value = value.slice(1, -1);
    }

    if (!key) {
      continue;
    }

    totalKeys += 1;

    if (key in secrets) {
      duplicateKeys.push(key);
    }

    secrets[key] = value;
  }

  return { secrets, duplicateKeys, totalKeys };
}

export function serializeDotenv(secrets: Record<string, string>): string {
  return Object.entries(secrets)
    .map(([key, value]) => `${key}=${value}`)
    .join('\n');
}
