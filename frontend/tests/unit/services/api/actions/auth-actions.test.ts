import { describe, it, expect, vi, afterEach } from 'vitest';
import { apiClient } from '@/services/api/client';
import { getAuthConfig, getMe, login, logout } from '@/services/api/actions/auth-actions';

afterEach(() => {
  vi.restoreAllMocks();
});

describe('auth-actions', () => {
  it('getAuthConfig calls GET /auth/config without X-Requested-With', async () => {
    const get = vi.spyOn(apiClient, 'get').mockResolvedValue({ data: { auth_enabled: true } });
    await getAuthConfig();
    expect(get).toHaveBeenCalledWith('/auth/config', expect.anything());
    const headers = get.mock.calls[0]?.[1]?.headers as Record<string, string>;
    expect(headers['X-Requested-With']).toBeUndefined();
  });

  it('getMe calls GET /auth/me', async () => {
    const get = vi.spyOn(apiClient, 'get').mockResolvedValue({ data: { username: 'a' } });
    const res = await getMe();
    expect(get).toHaveBeenCalledWith('/auth/me', expect.anything());
    expect(res.data.username).toBe('a');
  });

  it('login posts credentials to /auth/login with X-Requested-With', async () => {
    const post = vi.spyOn(apiClient, 'post').mockResolvedValue({ data: { user: {} } });
    await login({ username: 'u', password: 'p' });
    expect(post).toHaveBeenCalledWith(
      '/auth/login',
      { username: 'u', password: 'p' },
      { headers: expect.objectContaining({ 'X-Requested-With': 'XMLHttpRequest' }) }
    );
  });

  it('logout posts to /auth/logout with X-Requested-With', async () => {
    const post = vi.spyOn(apiClient, 'post').mockResolvedValue({ data: { message: 'Logged out' } });
    await logout();
    expect(post).toHaveBeenCalledWith(
      '/auth/logout',
      undefined,
      { headers: expect.objectContaining({ 'X-Requested-With': 'XMLHttpRequest' }) }
    );
  });

  it.each([
    ['getAuthConfig', 'get', () => getAuthConfig()],
    ['getMe', 'get', () => getMe()],
    ['login', 'post', () => login({ username: 'u', password: 'p' })],
    ['logout', 'post', () => logout()],
  ] as const)('%s re-throws client errors', async (_name, method, call) => {
    vi.spyOn(apiClient, method).mockRejectedValue(new Error('boom'));
    await expect(call()).rejects.toThrow('boom');
  });
});
