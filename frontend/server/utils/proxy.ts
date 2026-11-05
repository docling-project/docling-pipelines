import axios, { type AxiosResponse, type Method, type ResponseType } from 'axios';
import type { Response } from 'express';
import { log4js, logUtil } from '../../src/utils/logger';
import { BODY_HEADERS, NO_BODY_HEADERS } from '../controllers/http-headers';

const logger = log4js.getLogger('bff.proxy');

interface ProxyRequestOptions {
  method: Method;
  /** Backend path including any query string, e.g. `/api/v1/flows?limit=10`. */
  path: string;
  /** Request body. When defined, JSON body headers are used. */
  body?: unknown;
  /** Overrides the default `Accept` header. */
  accept?: string;
  /** Axios response type, e.g. `stream` for file downloads. */
  responseType?: ResponseType;
}

interface ProxyErrorOptions {
  res: Response;
  err: unknown;
  /** Controller logger, so the error is attributed to the calling controller. */
  logger: ReturnType<typeof log4js.getLogger>;
  /** Message sent to the client (and logged) when the backend gave no response body. */
  fallbackMessage: string;
}

/**
 * Sends a request to the Python FastAPI backend (`BACKEND_API_URL`).
 * Returns the raw Axios response so callers can choose how to forward it.
 */
export const proxyRequest = async ({
  method,
  path,
  body,
  accept,
  responseType,
}: ProxyRequestOptions): Promise<AxiosResponse> => {
  const url = `${process.env.BACKEND_API_URL}${path}`;
  logUtil.debug({ logger, message: 'Proxying request', data: { method, url } });

  const headers = { ...(body !== undefined ? BODY_HEADERS : NO_BODY_HEADERS) };
  if (accept) headers.Accept = accept;

  return axios.request({ method, url, data: body, headers, responseType });
};

/**
 * Logs a failed upstream call and replies to the client.
 * Forwards the backend status and body when the backend answered,
 * otherwise (network failure, timeout, unexpected error) replies 500
 * with `{ error: fallbackMessage }`.
 */
export const handleProxyError = ({ res, err, logger: controllerLogger, fallbackMessage }: ProxyErrorOptions): void => {
  const upstreamStatus = axios.isAxiosError(err) ? err.response?.status : undefined;
  const upstreamData: unknown = axios.isAxiosError(err) ? err.response?.data : undefined;
  const errorMessage = err instanceof Error ? err.message : String(err);

  logUtil.error({ logger: controllerLogger, message: fallbackMessage, data: errorMessage });

  res.status(upstreamStatus ?? 500).json(upstreamData ?? { error: fallbackMessage });
};
