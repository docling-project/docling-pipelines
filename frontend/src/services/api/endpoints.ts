/**
 * API endpoint paths.
 *
 * Auth endpoints live under `/auth/*` on the same origin as the page
 * (the backend in production, the Vite proxy in dev). They are not part of `/api/v1`.
 */

/** Authentication endpoints served by the backend. */
export const AUTH_ENDPOINTS = {
  CONFIG: '/auth/config',
  ME: '/auth/me',
  LOGIN: '/auth/login',
  LOGOUT: '/auth/logout',
} as const;
