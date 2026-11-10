/**
 * Axios HTTP Client Configuration
 *
 * Configured axios instance with interceptors for:
 * - Request/response logging
 * - Error handling
 */

import axios, { type AxiosInstance, type AxiosError, type InternalAxiosRequestConfig, type AxiosResponse } from 'axios';
import { createIntl, createIntlCache } from 'react-intl';
import { log4js, logUtil } from '@/utils/logger';
import { DEFAULT_LOCALE } from '@/i18n';
import { messages } from './client.messages';

const logger = log4js.getLogger('api.client');

// The client runs outside React, so it cannot use useIntl. Only the default locale is
// supported today; the message ids still live in messages_en.json for translation.
const intl = createIntl({ locale: DEFAULT_LOCALE, defaultLocale: DEFAULT_LOCALE }, createIntlCache());

/**
 * Create configured axios instance.
 *
 *   dev (npm run dev)      — Vite proxy forwards /api/* to BFF:3001 (BFF proxies to FastAPI /api/v1/*)
 *                            and /auth/* straight to FastAPI (BACKEND_API_URL, default :8080)
 *   production (npm start) — BFF serves on 3001; proxies /api/* to FastAPI /api/v1/*;
 *                            /auth/* is never routed to the BFF
 *   wheel (test_server.py) — FastAPI serves /auth/* itself and reverse-proxies /api/* to the BFF
 *                            at BFF_PORT (default 3001)
 *   Compose / Kubernetes   — a custom ingress must route /ui and /auth to FastAPI, not to the BFF
 */
export const apiClient: AxiosInstance = axios.create({
  timeout: 10000,
  withCredentials: true,
  headers: {
    'Content-Type': 'application/json',
  },
});

/**
 * Request Interceptor - Logs outgoing requests
 */
apiClient.interceptors.request.use(
  (config: InternalAxiosRequestConfig) => {
    logUtil.debug({
      logger,
      message: 'Outgoing request',
      data: { method: config.method, url: config.url, baseURL: config.baseURL },
    });

    const method = config.method?.toUpperCase();
    if (method && ['POST', 'PUT', 'PATCH', 'DELETE'].includes(method)) {
      config.headers.set('X-Requested-With', 'XMLHttpRequest');
    }

    return config;
  },
  (error: AxiosError) => {
    logUtil.error({
      logger,
      message: 'Request error',
      data: { method: error.config?.method, url: error.config?.url, error: error.message },
    });
    return Promise.reject(error);
  }
);

let isRedirecting = false;

/**
 * Response Interceptor - Logs responses and handles errors
 */
apiClient.interceptors.response.use(
  (response: AxiosResponse) => {
    logUtil.debug({
      logger,
      message: 'Response received',
      data: { method: response.config.method, url: response.config.url, status: response.status, statusText: response.statusText },
    });

    // Reset redirect latch on successful auth/login/me calls
    const url = response.config.url ?? '';
    if (url.endsWith('/auth/login') || url.endsWith('/auth/me')) {
      isRedirecting = false;
    }

    return response;
  },
  async (error: AxiosError) => {
    if (axios.isCancel(error)) {
      // Deliberately aborted request - not an error worth logging.
      return Promise.reject(error);
    }

    const status = error.response?.status;
    const url = error.config?.url ?? '';

    if (status === 401) {
      const isLogin = url.endsWith('/auth/login');

      // Resolve dependencies dynamically to avoid circular references during store creation
      const { store } = await import('@/store');
      const { logoutUser } = await import('@/slices/authSlice');

      const authState = store.getState().auth;
      const isInitialMe = url.endsWith('/auth/me') && (authState.status === 'loading' || authState.status === 'idle');

      if (!isLogin && !isInitialMe) {
        if (!isRedirecting) {
          isRedirecting = true;

          // Clear auth state
          void store.dispatch(logoutUser());

          // Navigate to login page outside of React
          const currentPath = window.location.pathname;
          const pathWithoutBasename = currentPath.startsWith('/ui') ? currentPath.slice(3) : currentPath;
          const returnTo = encodeURIComponent(pathWithoutBasename + window.location.search);
          window.location.assign(`/ui/login?return_to=${returnTo}`);
        }
      }
    } else if (status === 403) {
      const { store } = await import('@/store');
      const { addNotification } = await import('@/slices/notificationsSlice');

      store.dispatch(
        addNotification({
          kind: 'error',
          title: intl.formatMessage(messages.permissionDeniedTitle),
          subtitle: intl.formatMessage(messages.permissionDeniedSubtitle),
        })
      );
    }

    if (error.response) {
      logUtil.error({
        logger,
        message: 'Response error',
        data: {
          method: error.config?.method,
          url: error.config?.url,
          status: error.response.status,
          statusText: error.response.statusText,
          data: error.response.data,
        },
      });
    } else if (error.request) {
      logUtil.error({
        logger,
        message: 'No response received from server',
        data: { method: error.config?.method, url: error.config?.url },
      });
    } else {
      logUtil.error({
        logger,
        message: 'Request setup error',
        data: { method: error.config?.method, url: error.config?.url, message: error.message },
      });
    }
    return Promise.reject(error);
  }
);

export default apiClient;
