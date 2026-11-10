/**
 * Loopback by default so a locally started BFF is not reachable from other
 * hosts. Container images set BFF_HOST=0.0.0.0 so Compose peers and
 * Kubernetes probes on the pod address can reach it.
 */
export const DEFAULT_BFF_HOST = '127.0.0.1';

export const resolveBffHost = (env: Record<string, string | undefined> = process.env): string =>
  env.BFF_HOST?.trim() || DEFAULT_BFF_HOST;
