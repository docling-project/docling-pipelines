/**
 * Auth Actions
 *
 * HTTP calls to the backend `/auth/*` endpoints (same origin, not `/api/v1`).
 * The session lives in an HttpOnly cookie, so no token is handled here.
 */

import { type AxiosResponse } from 'axios';
import { log4js, logUtil } from '@/utils/logger';
import type { AuthConfigResponse, AuthUser, LoginRequest, LoginResponse } from '@/types';
import { apiClient } from '../client';
import { AUTH_ENDPOINTS } from '../endpoints';

const logger = log4js.getLogger('auth.actions');

const READ_HEADERS = {
  'Accept': 'application/json',
};

/** Cookie writes need a non-empty `X-Requested-With` header (CSRF defence). */
const WRITE_HEADERS = {
  'Accept': 'application/json',
  'X-Requested-With': 'XMLHttpRequest',
};

/**
 * Fetches the public authentication setup.
 *
 * @returns Axios response containing the {@link AuthConfigResponse}.
 * @throws Re-throws the Axios error on failure.
 *
 * Endpoint: GET /auth/config
 */
export const getAuthConfig = async (): Promise<AxiosResponse<AuthConfigResponse>> => {
  try {
    return await apiClient.get<AuthConfigResponse>(AUTH_ENDPOINTS.CONFIG, { headers: READ_HEADERS });
  } catch (error) {
    logUtil.error({ logger, message: 'Failed to fetch auth config', data: error });
    throw error;
  }
};

/**
 * Fetches the user of the current session.
 *
 * @returns Axios response containing the {@link AuthUser}.
 * @throws Re-throws the Axios error (401 when there is no session and auth is enabled).
 *
 * Endpoint: GET /auth/me
 */
export const getMe = async (): Promise<AxiosResponse<AuthUser>> => {
  try {
    return await apiClient.get<AuthUser>(AUTH_ENDPOINTS.ME, { headers: READ_HEADERS });
  } catch (error) {
    logUtil.error({ logger, message: 'Failed to fetch current user', data: error });
    throw error;
  }
};

/**
 * Signs in with username and password. The server sets the session cookie.
 *
 * @param credentials - Username and password.
 * @returns Axios response containing the {@link LoginResponse}.
 * @throws Re-throws the Axios error (401 bad credentials, 429 throttled, 503 not configured).
 *
 * Endpoint: POST /auth/login
 */
export const login = async (
  credentials: LoginRequest
): Promise<AxiosResponse<LoginResponse>> => {
  try {
    return await apiClient.post<LoginResponse>(AUTH_ENDPOINTS.LOGIN, credentials, {
      headers: WRITE_HEADERS,
    });
  } catch (error) {
    logUtil.error({ logger, message: 'Failed to log in', data: { error } });
    throw error;
  }
};

/**
 * Signs out. The server clears the session cookie, with or without a valid session.
 *
 * @returns Axios response containing the confirmation message.
 * @throws Re-throws the Axios error on failure.
 *
 * Endpoint: POST /auth/logout
 */
export const logout = async (): Promise<AxiosResponse<{ message: string }>> => {
  try {
    return await apiClient.post<{ message: string }>(AUTH_ENDPOINTS.LOGOUT, undefined, {
      headers: WRITE_HEADERS,
    });
  } catch (error) {
    logUtil.error({ logger, message: 'Failed to log out', data: error });
    throw error;
  }
};
