const LOG_LEVELS = { debug: 0, info: 1, warn: 2, error: 3 } as const;
type LogLevel = keyof typeof LOG_LEVELS;

// Competition integration: never render an active BYOK secret in upstream logs.
const transientSecrets = new Map<string, number>();
export function registerTransientLogSecrets(values: Array<string | undefined>): () => void {
  const secrets = values.filter((value): value is string => Boolean(value));
  for (const value of secrets) transientSecrets.set(value, (transientSecrets.get(value) ?? 0) + 1);
  return () => {
    for (const value of secrets) {
      const remaining = (transientSecrets.get(value) ?? 1) - 1;
      if (remaining > 0) transientSecrets.set(value, remaining);
      else transientSecrets.delete(value);
    }
  };
}

function getMinLevel(): LogLevel {
  const env = (process.env.LOG_LEVEL ?? 'info').toLowerCase();
  return env in LOG_LEVELS ? (env as LogLevel) : 'info';
}

function isJsonFormat(): boolean {
  return process.env.LOG_FORMAT === 'json';
}

function formatLine(level: LogLevel, tag: string, args: unknown[]): string {
  const timestamp = new Date().toISOString();
  const upperLevel = level.toUpperCase();
  let msg = args
    .map((a) =>
      a instanceof Error ? (a.stack ?? a.message) : typeof a === 'string' ? a : JSON.stringify(a),
    )
    .join(' ');
  for (const secret of transientSecrets.keys()) msg = msg.split(secret).join('[REDACTED]');

  if (isJsonFormat()) {
    return JSON.stringify({ timestamp, level: upperLevel, tag, message: msg });
  }
  return `[${timestamp}] [${upperLevel}] [${tag}] ${msg}`;
}

export function createLogger(tag: string) {
  const emit = (level: LogLevel, args: unknown[]) => {
    if (LOG_LEVELS[level] < LOG_LEVELS[getMinLevel()]) return;

    const line = formatLine(level, tag, args);

    // Console output
    const fn =
      level === 'debug'
        ? console.debug
        : level === 'warn'
          ? console.warn
          : level === 'error'
            ? console.error
            : console.log;
    fn(line);
  };

  return {
    debug: (...args: unknown[]) => emit('debug', args),
    info: (...args: unknown[]) => emit('info', args),
    warn: (...args: unknown[]) => emit('warn', args),
    error: (...args: unknown[]) => emit('error', args),
  };
}
