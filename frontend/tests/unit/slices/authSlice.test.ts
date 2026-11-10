import { describe, it, expect, vi, beforeEach } from 'vitest';
import { configureStore } from '@reduxjs/toolkit';
import authReducer, { bootstrapAuth, loginUser, logoutUser } from '@/slices/authSlice';
import * as authActions from '@/services/api/actions/auth-actions';
import type { AuthConfigResponse, AuthUser } from '@/types';

vi.mock('@/services/api/actions/auth-actions', () => ({
  getAuthConfig: vi.fn(),
  getMe: vi.fn(),
  login: vi.fn(),
  logout: vi.fn(),
}));

const mocked = vi.mocked(authActions);

const user: AuthUser = { username: 'alice', email: 'a@x.io', full_name: 'Alice', roles: ['editor'] };
const enabledConfig: AuthConfigResponse = {
  auth_enabled: true,
  credential_login: true,
  providers: [{ name: 'google', display_name: 'Google', authorize_url: '/auth/oauth2/authorize?provider=google' }],
};

const makeStore = () => configureStore({ reducer: { auth: authReducer } });
const ok = <T,>(data: T) => ({ data }) as never;
const httpError = (status: number, detail?: string, headers: Record<string, string> = {}) =>
  Object.assign(new Error(`status ${status}`), { response: { status, data: detail ? { detail } : {}, headers } });

beforeEach(() => {
  vi.clearAllMocks();
});

describe('authSlice', () => {
  it('initial state is idle with no user', () => {
    const state = authReducer(undefined, { type: '@@INIT' });
    expect(state.status).toBe('idle');
    expect(state.user).toBeNull();
    expect(state.error).toBeNull();
  });

  describe('bootstrapAuth', () => {
    it('sets status to loading while pending', () => {
      mocked.getAuthConfig.mockReturnValue(new Promise(() => undefined));
      const store = makeStore();
      void store.dispatch(bootstrapAuth());
      expect(store.getState().auth.status).toBe('loading');
    });

    it('restores a signed-in session', async () => {
      mocked.getAuthConfig.mockResolvedValue(ok(enabledConfig));
      mocked.getMe.mockResolvedValue(ok(user));
      const store = makeStore();
      await store.dispatch(bootstrapAuth());
      const { auth } = store.getState();
      expect(auth.status).toBe('authenticated');
      expect(auth.user).toEqual(user);
      expect(auth.authEnabled).toBe(true);
      expect(auth.credentialLogin).toBe(true);
      expect(auth.providers).toEqual(enabledConfig.providers);
    });

    it('is unauthenticated without error on 401 from /auth/me', async () => {
      mocked.getAuthConfig.mockResolvedValue(ok(enabledConfig));
      mocked.getMe.mockRejectedValue(httpError(401, 'Not authenticated'));
      const store = makeStore();
      await store.dispatch(bootstrapAuth());
      const { auth } = store.getState();
      expect(auth.status).toBe('unauthenticated');
      expect(auth.user).toBeNull();
      expect(auth.error).toBeNull();
      expect(auth.providers).toEqual(enabledConfig.providers);
    });

    it('treats auth disabled as authenticated admin and skips /auth/me', async () => {
      mocked.getAuthConfig.mockResolvedValue(
        ok({ auth_enabled: false, credential_login: false, providers: [] })
      );
      const store = makeStore();
      await store.dispatch(bootstrapAuth());
      const { auth } = store.getState();
      expect(mocked.getMe).not.toHaveBeenCalled();
      expect(auth.status).toBe('authenticated');
      expect(auth.authEnabled).toBe(false);
      expect(auth.user?.roles).toContain('admin');
    });

    it('stores an error when /auth/config fails', async () => {
      mocked.getAuthConfig.mockRejectedValue(httpError(500, 'Server down'));
      const store = makeStore();
      await store.dispatch(bootstrapAuth());
      const { auth } = store.getState();
      expect(auth.status).toBe('unauthenticated');
      expect(auth.error).toBe('Server down');
    });

    it('stores an error when /auth/me fails with a non-401', async () => {
      mocked.getAuthConfig.mockResolvedValue(ok(enabledConfig));
      mocked.getMe.mockRejectedValue(httpError(500, 'Oops'));
      const store = makeStore();
      await store.dispatch(bootstrapAuth());
      expect(store.getState().auth.status).toBe('unauthenticated');
      expect(store.getState().auth.error).toBe('Oops');
    });
  });

  describe('loginUser', () => {
    it('stores only the user and never the access token', async () => {
      mocked.login.mockResolvedValue(
        ok({ access_token: 'secret-token', token_type: 'bearer', user })
      );
      const store = makeStore();
      await store.dispatch(loginUser({ username: 'alice', password: 'pw' })); // pragma: allowlist secret
      const { auth } = store.getState();
      expect(auth.status).toBe('authenticated');
      expect(auth.user).toEqual(user);
      expect(JSON.stringify(auth)).not.toContain('secret-token');
    });

    it('stores the server message on 401', async () => {
      mocked.login.mockRejectedValue(httpError(401, 'Invalid credentials'));
      const store = makeStore();
      await store.dispatch(loginUser({ username: 'alice', password: 'bad' })); // pragma: allowlist secret
      const { auth } = store.getState();
      expect(auth.status).toBe('unauthenticated');
      expect(auth.user).toBeNull();
      expect(auth.error).toBe('Invalid credentials');
      expect(auth.errorStatus).toBe(401);
      expect(auth.retryAfter).toBeNull();
    });

    it('stores retry-after on 429', async () => {
      mocked.login.mockRejectedValue(httpError(429, 'Too many failed login attempts.', { 'retry-after': '42' }));
      const store = makeStore();
      await store.dispatch(loginUser({ username: 'alice', password: 'bad' })); // pragma: allowlist secret
      const { auth } = store.getState();
      expect(auth.errorStatus).toBe(429);
      expect(auth.retryAfter).toBe(42);
      expect(auth.status).toBe('unauthenticated');
    });

    it('stores the message on 503', async () => {
      mocked.login.mockRejectedValue(httpError(503, 'Authentication service not configured'));
      const store = makeStore();
      await store.dispatch(loginUser({ username: 'alice', password: 'pw' })); // pragma: allowlist secret
      const { auth } = store.getState();
      expect(auth.errorStatus).toBe(503);
      expect(auth.error).toBe('Authentication service not configured');
      expect(auth.status).toBe('unauthenticated');
    });

    it('clears a previous error when a new login starts', async () => {
      mocked.login.mockRejectedValueOnce(httpError(401, 'Invalid credentials'));
      const store = makeStore();
      await store.dispatch(loginUser({ username: 'a', password: 'x' })); // pragma: allowlist secret
      mocked.login.mockReturnValue(new Promise(() => undefined));
      void store.dispatch(loginUser({ username: 'a', password: 'y' })); // pragma: allowlist secret
      expect(store.getState().auth.error).toBeNull();
    });
  });

  describe('logoutUser', () => {
    const signedIn = async () => {
      mocked.login.mockResolvedValue(ok({ access_token: 't', token_type: 'bearer', user }));
      const store = makeStore();
      await store.dispatch(loginUser({ username: 'alice', password: 'pw' })); // pragma: allowlist secret
      return store;
    };

    it('clears the user', async () => {
      mocked.logout.mockResolvedValue(ok({ message: 'Logged out' }));
      const store = await signedIn();
      await store.dispatch(logoutUser());
      expect(mocked.logout).toHaveBeenCalledTimes(1);
      expect(store.getState().auth.user).toBeNull();
      expect(store.getState().auth.status).toBe('unauthenticated');
    });

    it('clears the user even when the request fails', async () => {
      mocked.logout.mockRejectedValue(httpError(500));
      const store = await signedIn();
      await store.dispatch(logoutUser());
      expect(store.getState().auth.user).toBeNull();
      expect(store.getState().auth.status).toBe('unauthenticated');
    });
  });
});
