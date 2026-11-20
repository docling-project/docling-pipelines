/**
 * Axios HTTP Client Configuration
 *
 * Configured axios instance with interceptors for:
 * - Request/response logging
 * - Error handling
 */

import axios, { type AxiosInstance, type AxiosError, type InternalAxiosRequestConfig, type AxiosResponse } from 'axios';
import { createIntl, createIntlCache, type IntlShape } from 'react-intl';
import { log4js, logUtil } from '@/utils/logger';
import { DEFAULT_LOCALE } from '@/i18n';
import { addNotification } from '@/slices/notificationsSlice';
import { messages } from './client.messages';

const logger = log4js.getLogger('api.client');

/** Minimal store interface needed by the HTTP client interceptors. */
export interface ApiClientStore {
  getState: () => { auth: { status: string } };
  dispatch: (action: unknown) => unknown;
}

/** Configuration injected at app startup via {@link configureApiClient}. */
export interface ApiClientConfig {
  store?: ApiClientStore;
  intl?: IntlShape;
}

let configuredStore: ApiClientStore | null = null;
let configuredIntl: IntlShape | null = null;
let fallbackIntl: IntlShape | null = null;
let isRedirecting = false;

/**
 * Configures the API client with the application Redux store and react-intl instance.
 * Called once during startup in `main.tsx` to avoid circular module imports and
 * to keep interceptor notifications aligned with the active locale.
 */
export function configureApiClient(config: ApiClientConfig): void {
  if (config.store !== undefined) {
    configuredStore = config.store;
  }
  if (config.intl !== undefined) {
    configuredIntl = config.intl;
  }
  isRedirecting = false;
}

/** Resets the 401 redirect latch (e.g. on bfcache restore or between tests). */
export function resetAuthRedirectLatch(): void {
  isRedirecting = false;
}

if (typeof window !== 'undefined') {
  window.addEventListener('pageshow', () => {
    isRedirecting = false;
  });
}

function getIntl(): IntlShape {
  if (configuredIntl) {
    return configuredIntl;
  }
  fallbackIntl ??= createIntl(
    { locale: DEFAULT_LOCALE, defaultLocale: DEFAULT_LOCALE },
    createIntlCache()
  );
  return fallbackIntl;
}

async function getStore(): Promise<ApiClientStore> {
  if (configuredStore) {
    return configuredStore;
  }
  // Safe fallback for isolated unit tests that import apiClient without calling configureApiClient.
  const { store } = await import('@/store');
  return store;
}

/**
 * Strips the `/ui` router basename from a pathname without touching paths
 * that merely share the prefix (such as `/uix/foo`).
 */
export function stripUiBasename(pathname: string): string {
  if (pathname === '/ui') {
    return '/';
  }
  if (pathname.startsWith('/ui/')) {
    return pathname.slice(3);
  }
  return pathname.startsWith('/') ? pathname : `/${pathname}`;
}

function stripQueryAndHash(url: string): string {
  return url.split(/[?#]/)[0] ?? '';
}

function isOnLoginRoute(pathname: string): boolean {
  const normalized = stripUiBasename(pathname);
  return normalized === '/login' || normalized.startsWith('/login/');
}

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
    const cleanUrl = stripQueryAndHash(response.config.url ?? '');
    if (cleanUrl.endsWith('/auth/login') || cleanUrl.endsWith('/auth/me')) {
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
    const cleanUrl = stripQueryAndHash(error.config?.url ?? '');

    if (status === 401) {
      const isExemptEndpoint =
        cleanUrl.endsWith('/auth/login') ||
        cleanUrl.endsWith('/auth/logout') ||
        cleanUrl.endsWith('/auth/config');

      if (!isExemptEndpoint && !isOnLoginRoute(window.location.pathname)) {
        const store = await getStore();
        const authStatus = store.getState().auth.status;
        const isInitialMe =
          cleanUrl.endsWith('/auth/me') && (authStatus === 'loading' || authStatus === 'idle');

        if (!isInitialMe && !isRedirecting) {
          isRedirecting = true;

          // Synchronously clear local auth & cached domain state before navigating so
          // cleanup cannot race with window.location.assign or trigger a failing /auth/logout.
          store.dispatch({ type: 'auth/clearSession' });

          const pathWithoutBasename = stripUiBasename(window.location.pathname);
          const returnTo = encodeURIComponent(pathWithoutBasename + window.location.search);
          try {
            window.location.assign(`/ui/login?return_to=${returnTo}`);
          } catch {
            isRedirecting = false;
          }
        }
      }
    } else if (status === 403) {
      const store = await getStore();
      const intl = getIntl();

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
