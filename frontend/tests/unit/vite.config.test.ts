import { describe, it, expect, vi, beforeEach } from 'vitest';

// vite pulls in esbuild, which does not load under jsdom. Only defineConfig
// (identity) and loadEnv (stubbed) are needed to exercise the proxy wiring.
const loadEnv = vi.hoisted(() => vi.fn());
vi.mock('vite', () => ({
  defineConfig: (config: unknown) => config,
  loadEnv,
}));
vi.mock('@vitejs/plugin-react', () => ({ default: () => ({ name: 'react-stub' }) }));

import viteConfig, { DEFAULT_BACKEND_API_URL, resolveBackendApiUrl } from '../../vite.config';

type ProxyConfig = Record<string, { target: string; changeOrigin: boolean }>;

const proxyFor = (mode: string): ProxyConfig => {
  const factory = viteConfig as unknown as (env: { mode: string; command: string }) => { server: { proxy: ProxyConfig } };
  return factory({ mode, command: 'serve' }).server.proxy;
};

describe('vite dev proxy', () => {
  beforeEach(() => {
    loadEnv.mockReset();
  });

  it('defaults the /auth target to the REST API port 8080', () => {
    loadEnv.mockReturnValue({});

    expect(DEFAULT_BACKEND_API_URL).toBe('http://localhost:8080');
    expect(resolveBackendApiUrl('development')).toBe('http://localhost:8080');
    expect(proxyFor('development')['/auth']).toEqual({ target: 'http://localhost:8080', changeOrigin: true });
  });

  it('loads every variable (empty prefix) for the given mode', () => {
    loadEnv.mockReturnValue({});

    proxyFor('staging');

    expect(loadEnv).toHaveBeenCalledWith('staging', expect.any(String), '');
  });

  it('uses BACKEND_API_URL for /auth when configured', () => {
    loadEnv.mockReturnValue({ BACKEND_API_URL: 'http://api.internal:9000' });

    expect(proxyFor('development')['/auth']?.target).toBe('http://api.internal:9000');
  });

  it('keeps /api pointed at the BFF', () => {
    loadEnv.mockReturnValue({});

    expect(proxyFor('development')['/api']?.target).toBe('http://localhost:3001');
  });
});
