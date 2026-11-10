/**
 * Axios HTTP Client Configuration
 *
 * Configured axios instance with interceptors for:
 * - Request/response logging
 * - Error handling
 */

import axios, { type AxiosInstance, type AxiosError, type InternalAxiosRequestConfig, type AxiosResponse } from 'axios';
import { log4js, logUtil } from '@/utils/logger';

const logger = log4js.getLogger('api.client');

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
    return response;
  },
  (error: AxiosError) => {
    if (axios.isCancel(error)) {
      // Deliberately aborted request - not an error worth logging.
      return Promise.reject(error);
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
