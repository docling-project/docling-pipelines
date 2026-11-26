/**
 * @fileoverview Selectors for accessing authentication state from the Redux store.
 * All selectors read from `state.auth`, owned by `authSlice`.
 */

import type { RootState } from '@/store';
import type { AuthProvider, AuthState, AuthStatus, AuthUser } from '@/types';

/** Selects the entire auth state slice. */
export const selectAuthState = (state: RootState): AuthState => state.auth;

/** Selects the signed-in user, or `null`. */
export const selectAuthUser = (state: RootState): AuthUser | null => state.auth.user;

/** Selects the lifecycle status of the auth state. */
export const selectAuthStatus = (state: RootState): AuthStatus => state.auth.status;

/** Selects whether authentication is enabled on the backend. */
export const selectAuthEnabled = (state: RootState): boolean => state.auth.authEnabled;

/** Selects whether username/password login is enabled. */
export const selectCredentialLogin = (state: RootState): boolean => state.auth.credentialLogin;

/** Selects the configured OIDC providers. */
export const selectAuthProviders = (state: RootState): AuthProvider[] => state.auth.providers;

/** Selects the last authentication error message, or `null`. */
export const selectAuthError = (state: RootState): string | null => state.auth.error;

/** Selects the retry-after duration in seconds after a 429 response, or `null`. */
export const selectRetryAfterSeconds = (state: RootState): number | null => state.auth.retryAfter;
