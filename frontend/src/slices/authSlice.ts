/**
 * @fileoverview Redux slice for authentication state.
 * Bootstraps from `/auth/config` and `/auth/me`, and handles login and logout.
 * Only the `user` is stored. The session token lives in an HttpOnly cookie and
 * the `access_token` in the login response is deliberately ignored.
 */

import { createSlice, createAsyncThunk } from '@reduxjs/toolkit';
import type { AuthState, AuthUser, AuthErrorPayload, AuthConfigResponse, LoginRequest } from '@/types';
import {
  getAuthConfig as apiGetAuthConfig,
  getMe as apiGetMe,
  login as apiLogin,
  logout as apiLogout,
} from '@/services/api/actions/auth-actions';

/** Principal used when the backend reports that authentication is disabled. */
export const LOCAL_ADMIN_USER: AuthUser = {
  username: '<local-principal>',
  email: '',
  full_name: '',
  roles: ['admin'],
};

const initialState: AuthState = {
  user: null,
  authEnabled: true,
  providers: [],
  credentialLogin: false,
  status: 'idle',
  error: null,
  errorStatus: null,
  retryAfter: null,
};

type AxiosLikeError = {
  response?: { status?: number; data?: { detail?: unknown }; headers?: Record<string, unknown> };
  message?: string;
};

/**
 * Converts an unknown thrown value into an {@link AuthErrorPayload}.
 * @param error    - The caught value (usually an Axios error).
 * @param fallback - Message used when the server did not send one.
 */
function toErrorPayload(error: unknown, fallback: string): AuthErrorPayload {
  const e = error as AxiosLikeError;
  const detail = e?.response?.data?.detail;
  const rawRetry = e?.response?.headers?.['retry-after'];
  const retry = rawRetry === undefined ? NaN : Number(rawRetry);
  return {
    message: typeof detail === 'string' ? detail : (e?.message ?? fallback),
    status: e?.response?.status ?? null,
    retryAfter: Number.isFinite(retry) ? retry : null,
  };
}

/** Result of {@link bootstrapAuth}. */
export interface BootstrapResult {
  config: AuthConfigResponse;
  user: AuthUser | null;
}

/**
 * Loads `/auth/config` and, when auth is enabled, `/auth/me`.
 * A 401 from `/auth/me` resolves with `user: null` (no error, no redirect).
 * When auth is disabled no `/auth/me` request is made.
 */
export const bootstrapAuth = createAsyncThunk<BootstrapResult, void, { rejectValue: AuthErrorPayload }>(
  'auth/bootstrap',
  async (_arg, { rejectWithValue }) => {
    let config: AuthConfigResponse;
    try {
      config = (await apiGetAuthConfig()).data;
    } catch (error: unknown) {
      return rejectWithValue(toErrorPayload(error, 'Failed to load authentication configuration'));
    }
    if (!config.auth_enabled) {
      return { config, user: LOCAL_ADMIN_USER };
    }
    try {
      const user = (await apiGetMe()).data;
      return { config, user };
    } catch (error: unknown) {
      const payload = toErrorPayload(error, 'Failed to load the current user');
      if (payload.status === 401) {
        return { config, user: null };
      }
      return rejectWithValue(payload);
    }
  }
);

/**
 * Signs in with username and password and returns only the `user`.
 * Rejects with an {@link AuthErrorPayload} (401, 429 with `retryAfter`, 503).
 */
export const loginUser = createAsyncThunk<AuthUser, LoginRequest, { rejectValue: AuthErrorPayload }>(
  'auth/login',
  async (credentials, { rejectWithValue }) => {
    try {
      const response = await apiLogin(credentials);
      return response.data.user;
    } catch (error: unknown) {
      return rejectWithValue(toErrorPayload(error, 'Login failed'));
    }
  }
);

/**
 * Signs out. The user is cleared whether or not the request succeeds.
 */
export const logoutUser = createAsyncThunk<void, void>(
  'auth/logout',
  async () => {
    await apiLogout();
  }
);

const authSlice = createSlice({
  name: 'auth',
  initialState,
  reducers: {},
  extraReducers: (builder) => {
    builder
      .addCase(bootstrapAuth.pending, (state) => {
        state.status = 'loading';
        state.error = null;
      })
      .addCase(bootstrapAuth.fulfilled, (state, action) => {
        const { config, user } = action.payload;
        state.authEnabled = config.auth_enabled;
        state.credentialLogin = config.credential_login;
        state.providers = config.providers;
        state.user = user;
        state.status = user ? 'authenticated' : 'unauthenticated';
        state.error = null;
      })
      .addCase(bootstrapAuth.rejected, (state, action) => {
        state.user = null;
        state.status = 'unauthenticated';
        state.error = action.payload?.message ?? action.error.message ?? null;
      })
      .addCase(loginUser.pending, (state) => {
        state.error = null;
        state.errorStatus = null;
        state.retryAfter = null;
      })
      .addCase(loginUser.fulfilled, (state, action) => {
        state.user = action.payload;
        state.status = 'authenticated';
        state.error = null;
        state.errorStatus = null;
        state.retryAfter = null;
      })
      .addCase(loginUser.rejected, (state, action) => {
        state.user = null;
        state.status = 'unauthenticated';
        state.error = action.payload?.message ?? action.error.message ?? null;
        state.errorStatus = action.payload?.status ?? null;
        state.retryAfter = action.payload?.retryAfter ?? null;
      })
      .addMatcher(
        (action) => logoutUser.fulfilled.match(action) || logoutUser.rejected.match(action),
        (state) => {
          state.user = null;
          state.status = 'unauthenticated';
          state.error = null;
          state.errorStatus = null;
          state.retryAfter = null;
        }
      );
  },
});

export default authSlice.reducer;
