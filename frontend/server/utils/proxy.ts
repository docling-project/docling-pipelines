import { Readable } from 'node:stream';
import axios, { type AxiosResponse, type Method, type ResponseType } from 'axios';
import type { Response } from 'express';
import { log4js, logUtil } from '../../src/utils/logger';
import { BODY_HEADERS, NO_BODY_HEADERS } from '../constants/http-headers';

const logger = log4js.getLogger('bff.proxy');

type QueryValue = string | number | boolean | undefined | readonly string[];

/**
 * Thrown by `proxyRequest` when a path segment could change which backend
 * endpoint is called (`.`, `..` or empty). `handleProxyError` maps it to a 400.
 */
export class InvalidPathSegmentError extends Error {
  constructor(segment: string) {
    super(`Invalid path segment: "${segment}"`);
    this.name = 'InvalidPathSegmentError';
  }
}

interface ProxyRequestOptions {
  method: Method;
  /**
   * Backend path as separate segments, e.g. `['api', 'v1', 'flows', flowId]`.
   * Every segment is percent-encoded, so a route parameter cannot add query
   * parameters or extra path levels. Never build this from a pre-joined string.
   */
  path: readonly string[];
  /**
   * Query parameters. Values are encoded by `URLSearchParams`; `undefined` is
   * omitted and an array becomes repeated keys (`tags=a&tags=b`).
   */
  query?: Readonly<Record<string, QueryValue>>;
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

const encodePathSegment = (segment: string): string => {
  if (segment === '' || segment === '.' || segment === '..') {
    throw new InvalidPathSegmentError(segment);
  }
  return encodeURIComponent(segment);
};

const buildQueryString = (query: Readonly<Record<string, QueryValue>>): string => {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value === undefined) continue;
    if (typeof value === 'object') {
      value.forEach((item) => params.append(key, item));
    } else {
      params.append(key, String(value));
    }
  }
  return params.toString();
};

/**
 * Sends a request to the Python FastAPI backend (`BACKEND_API_URL`).
 * Returns the raw Axios response so callers can choose how to forward it.
 * Throws `InvalidPathSegmentError` for unsafe path segments.
 */
export const proxyRequest = async ({
  method,
  path,
  query,
  body,
  accept,
  responseType,
}: ProxyRequestOptions): Promise<AxiosResponse> => {
  const queryString = query ? buildQueryString(query) : '';
  const url = `${process.env.BACKEND_API_URL}/${path.map(encodePathSegment).join('/')}${queryString ? `?${queryString}` : ''}`;
  logUtil.debug({ logger, message: 'Proxying request', data: { method, url } });

  // Headers are built here and not accepted from callers, so a controller cannot
  // accidentally replace the defaults. `accept` is the only supported override.
  const headers = { ...(body !== undefined ? BODY_HEADERS : NO_BODY_HEADERS) };
  if (accept) headers.Accept = accept;

  return axios.request({ method, url, data: body, headers, responseType });
};

const MAX_ERROR_BODY_BYTES = 64 * 1024;

/**
 * Error bodies of requests made with `responseType: 'stream'` arrive as a Node stream,
 * which cannot be sent with `res.json()`. Reads at most `MAX_ERROR_BODY_BYTES` of it as text.
 */
const readStreamedBody = async (stream: Readable): Promise<string> => {
  const chunks: Buffer[] = [];
  let size = 0;
  try {
    for await (const chunk of stream) {
      const buffer = Buffer.isBuffer(chunk) ? chunk : Buffer.from(String(chunk));
      size += buffer.length;
      if (size > MAX_ERROR_BODY_BYTES) {
        stream.destroy();
        break;
      }
      chunks.push(buffer);
    }
  } catch {
    // A broken error stream is treated as an empty body; the caller falls back to its message.
  }
  return Buffer.concat(chunks).toString('utf8');
};

const parseJson = (text: string): unknown => {
  try {
    return text ? JSON.parse(text) : undefined;
  } catch {
    return undefined;
  }
};

/**
 * Logs a failed upstream call and replies to the client.
 * Forwards the backend status and body when the backend answered (streamed error bodies are
 * read first), otherwise (network failure, unexpected error) replies 500 with
 * `{ error: fallbackMessage }`. The backend body is also written to the server log, so the
 * detail of a failure is available there even when the client only sees the fallback.
 */
export const handleProxyError = async ({
  res,
  err,
  logger: controllerLogger,
  fallbackMessage,
}: ProxyErrorOptions): Promise<void> => {
  if (err instanceof InvalidPathSegmentError) {
    logUtil.warn({ logger: controllerLogger, message: fallbackMessage, data: err.message });
    res.status(400).json({ error: 'Invalid request path' });
    return;
  }

  const upstreamStatus = axios.isAxiosError(err) ? err.response?.status : undefined;
  let upstreamData: unknown = axios.isAxiosError(err) ? err.response?.data : undefined;
  let upstreamText: string | undefined;
  if (upstreamData instanceof Readable) {
    upstreamText = await readStreamedBody(upstreamData);
    upstreamData = parseJson(upstreamText);
  }
  const errorMessage = err instanceof Error ? err.message : String(err);

  logUtil.error({
    logger: controllerLogger,
    message: fallbackMessage,
    data: { error: errorMessage, status: upstreamStatus, upstream: upstreamData ?? upstreamText },
  });

  res.status(upstreamStatus ?? 500).json(upstreamData ?? { error: fallbackMessage });
};
