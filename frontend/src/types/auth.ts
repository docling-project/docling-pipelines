/**
 * Shared type definitions for the authentication domain.
 *
 * Covers the `/auth/*` wire types returned by the backend and the Redux
 * state shape of the auth slice. The access token is deliberately absent
 * from the state: the session lives in an HttpOnly cookie.
 */

// ── API wire types ───────────────────────────────────────────────────────

/** Roles the backend can assign to a user. */
export type AuthRole = 'viewer' | 'editor' | 'admin';

/** Authenticated user as returned by `GET /auth/me` and `POST /auth/login`. */
export interface AuthUser {
  username: string;
  email: string;
  full_name: string;
  roles: AuthRole[];
}

/** An OIDC provider advertised by `GET /auth/config`. */
export interface AuthProvider {
  name: string;
  display_name: string;
  /** Relative URL that starts the login with this provider. */
  authorize_url: string;
}

/** Response of `GET /auth/config`. */
export interface AuthConfigResponse {
  auth_enabled: boolean;
  credential_login: boolean;
  providers: AuthProvider[];
}

/** Request body of `POST /auth/login`. */
export interface LoginRequest {
  username: string;
  password: string;
}

/** Response of `POST /auth/login`. The `access_token` must never be stored. */
export interface LoginResponse {
  access_token: string;
  token_type: string;
  user: AuthUser;
}

// ── Redux state ──────────────────────────────────────────────────────────

/** Lifecycle status of the auth state. */
export type AuthStatus = 'idle' | 'loading' | 'authenticated' | 'unauthenticated';

/** Error details carried by a rejected auth thunk. */
export interface AuthErrorPayload {
  message: string;
  /** HTTP status of the failed request, when the server answered. */
  status: number | null;
  /** Seconds from the `Retry-After` header (429 only). */
  retryAfter: number | null;
}

/** State shape of the `auth` slice. */
export interface AuthState {
  user: AuthUser | null;
  authEnabled: boolean;
  providers: AuthProvider[];
  credentialLogin: boolean;
  status: AuthStatus;
  error: string | null;
  /** HTTP status of the last failed login, or `null`. */
  errorStatus: number | null;
  /** Seconds to wait before retrying after a 429, or `null`. */
  retryAfter: number | null;
}
