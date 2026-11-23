import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { DEFAULT_BFF_HOST, resolveBffHost } from '../../../server/bind-host';

describe('resolveBffHost', () => {
  it('defaults to loopback', () => {
    expect(DEFAULT_BFF_HOST).toBe('127.0.0.1');
    expect(resolveBffHost({})).toBe('127.0.0.1');
  });

  it('uses BFF_HOST when set', () => {
    expect(resolveBffHost({ BFF_HOST: '0.0.0.0' })).toBe('0.0.0.0');
  });

  it('falls back to loopback for an empty or blank BFF_HOST', () => {
    expect(resolveBffHost({ BFF_HOST: '' })).toBe('127.0.0.1');
    expect(resolveBffHost({ BFF_HOST: '  ' })).toBe('127.0.0.1');
  });
});

describe('server.ts listen', () => {
  const listen = vi.fn();

  beforeEach(() => {
    vi.resetModules();
    listen.mockReset();
    vi.stubEnv('BACKEND_API_URL', 'http://backend.test');
    vi.stubEnv('BFF_PORT', '3999');
    vi.doMock('dotenv', () => ({ default: { config: vi.fn() } }));
    vi.doMock('express', () => {
      const app = { use: vi.fn(), get: vi.fn(), listen };
      const express = Object.assign(() => app, {
        json: vi.fn(),
        Router: () => ({ get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), delete: vi.fn() }),
      });
      return { default: express };
    });
  });

  afterEach(() => {
    vi.unstubAllEnvs();
    vi.doUnmock('express');
    vi.doUnmock('dotenv');
  });

  it('binds to 127.0.0.1 when BFF_HOST is not set', async () => {
    vi.stubEnv('BFF_HOST', '');

    await import('../../../server/server');

    expect(listen).toHaveBeenCalledWith(3999, '127.0.0.1', expect.any(Function));
  });

  it('binds to BFF_HOST when set', async () => {
    vi.stubEnv('BFF_HOST', '0.0.0.0');

    await import('../../../server/server');

    expect(listen).toHaveBeenCalledWith(3999, '0.0.0.0', expect.any(Function));
  });
});
