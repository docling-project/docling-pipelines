import { Readable } from 'node:stream';
import axios, { AxiosError, type AxiosResponse } from 'axios';
import type { Response } from 'express';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { handleProxyError, InvalidPathSegmentError, proxyRequest } from '../../../server/utils/proxy';
import { queryString, queryStringList, routeParam } from '../../../server/utils/query';

const logger = {
  category: 'test',
  isDebugEnabled: () => false,
  isInfoEnabled: () => false,
  isWarnEnabled: () => false,
  isErrorEnabled: () => false,
} as unknown as Parameters<typeof handleProxyError>[0]['logger'];

const createRes = () => {
  const json = vi.fn();
  const status = vi.fn(() => ({ json }));
  return { res: { status } as unknown as Response, status, json };
};

describe('proxyRequest', () => {
  beforeEach(() => {
    process.env.BACKEND_API_URL = 'http://backend:8000';
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('prefixes the path with BACKEND_API_URL and uses no-body headers when body is undefined', async () => {
    const spy = vi.spyOn(axios, 'request').mockResolvedValue({ status: 200, data: {} } as AxiosResponse);

    await proxyRequest({ method: 'GET', path: ['api', 'v1', 'flows'] });

    expect(spy).toHaveBeenCalledWith({
      method: 'GET',
      url: 'http://backend:8000/api/v1/flows',
      data: undefined,
      headers: { Accept: 'application/json' },
      responseType: undefined,
    });
  });

  it('uses JSON body headers when a body is provided', async () => {
    const spy = vi.spyOn(axios, 'request').mockResolvedValue({ status: 201, data: {} } as AxiosResponse);

    await proxyRequest({ method: 'POST', path: ['api', 'v1', 'flows'], body: { name: 'a' } });

    expect(spy).toHaveBeenCalledWith(
      expect.objectContaining({
        data: { name: 'a' },
        headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
      }),
    );
  });

  it('allows overriding Accept and responseType for streamed downloads', async () => {
    const spy = vi.spyOn(axios, 'request').mockResolvedValue({ status: 200, data: {} } as AxiosResponse);

    await proxyRequest({ method: 'GET', path: ['report'], accept: 'text/csv', responseType: 'stream' });

    expect(spy).toHaveBeenCalledWith(
      expect.objectContaining({ headers: { Accept: 'text/csv' }, responseType: 'stream' }),
    );
  });

  describe('URL construction', () => {
    const urlOf = async (options: Parameters<typeof proxyRequest>[0]) => {
      const spy = vi.spyOn(axios, 'request').mockResolvedValue({ status: 200, data: {} } as AxiosResponse);
      await proxyRequest(options);
      return (spy.mock.calls[0]?.[0] as { url: string }).url;
    };

    it('percent-encodes route parameters so they cannot add query parameters', async () => {
      const url = await urlOf({ method: 'GET', path: ['api', 'v1', 'flows', 'abc?is_elyra=true'] });

      expect(url).toBe('http://backend:8000/api/v1/flows/abc%3Fis_elyra%3Dtrue');
    });

    it('percent-encodes slashes so a parameter cannot add path levels', async () => {
      const url = await urlOf({ method: 'GET', path: ['api', 'v1', 'flows', '../../operators/metadata'] });

      expect(url).toBe('http://backend:8000/api/v1/flows/..%2F..%2Foperators%2Fmetadata');
    });

    it.each(['.', '..', ''])('rejects the unsafe path segment "%s" without calling the backend', async (segment) => {
      const spy = vi.spyOn(axios, 'request').mockResolvedValue({ status: 200, data: {} } as AxiosResponse);

      await expect(proxyRequest({ method: 'GET', path: ['api', 'v1', 'flows', segment] })).rejects.toBeInstanceOf(
        InvalidPathSegmentError,
      );
      expect(spy).not.toHaveBeenCalled();
    });

    it('encodes query values built with & and =', async () => {
      const url = await urlOf({ method: 'GET', path: ['api', 'v1', 'flows'], query: { name: 'a&b=c', limit: '5' } });

      expect(url).toBe('http://backend:8000/api/v1/flows?name=a%26b%3Dc&limit=5');
    });

    it('sends arrays as repeated keys and omits undefined values', async () => {
      const url = await urlOf({
        method: 'GET',
        path: ['api', 'v1', 'flows'],
        query: { tags: ['x', 'y'], is_hidden: false, skipped: undefined },
      });

      expect(url).toBe('http://backend:8000/api/v1/flows?tags=x&tags=y&is_hidden=false');
    });
  });
});

describe('handleProxyError', () => {
  it('forwards upstream status and body when the backend replied', async () => {
    const { res, status, json } = createRes();
    const err = new AxiosError('Request failed', 'ERR_BAD_REQUEST', undefined, undefined, {
      status: 404,
      data: { detail: 'not found' },
    } as AxiosResponse);

    await handleProxyError({ res, err, logger, fallbackMessage: 'Failed to fetch flow' });

    expect(status).toHaveBeenCalledWith(404);
    expect(json).toHaveBeenCalledWith({ detail: 'not found' });
  });

  it('replies 500 with the fallback message for network errors', async () => {
    const { res, status, json } = createRes();

    await handleProxyError({ res, err: new AxiosError('connect ECONNREFUSED'), logger, fallbackMessage: 'Failed to fetch flow' });

    expect(status).toHaveBeenCalledWith(500);
    expect(json).toHaveBeenCalledWith({ error: 'Failed to fetch flow' });
  });

  it('replies 400 without contacting or leaking details when a path segment was rejected', async () => {
    const { res, status, json } = createRes();

    await handleProxyError({ res, err: new InvalidPathSegmentError('..'), logger, fallbackMessage: 'Failed to fetch flow' });

    expect(status).toHaveBeenCalledWith(400);
    expect(json).toHaveBeenCalledWith({ error: 'Invalid request path' });
  });

  const streamedError = (status: number, body: string) =>
    new AxiosError('Request failed', 'ERR_BAD_REQUEST', undefined, undefined, {
      status,
      data: Readable.from([Buffer.from(body)]),
    } as AxiosResponse);

  it('reads a streamed JSON error body instead of passing the stream to res.json()', async () => {
    const { res, status, json } = createRes();

    await handleProxyError({
      res,
      err: streamedError(404, '{"detail":"Job run not found"}'),
      logger,
      fallbackMessage: 'Failed to download job run report',
    });

    expect(status).toHaveBeenCalledWith(404);
    expect(json).toHaveBeenCalledWith({ detail: 'Job run not found' });
  });

  it('falls back to the fallback message when a streamed error body is not JSON', async () => {
    const { res, status, json } = createRes();

    await handleProxyError({
      res,
      err: streamedError(502, 'Bad gateway'),
      logger,
      fallbackMessage: 'Failed to download job run report',
    });

    expect(status).toHaveBeenCalledWith(502);
    expect(json).toHaveBeenCalledWith({ error: 'Failed to download job run report' });
  });

  it('stops reading a streamed error body after the size cap', async () => {
    const { res, json } = createRes();
    const stream = Readable.from([Buffer.alloc(40 * 1024, 'x'), Buffer.alloc(40 * 1024, 'x'), Buffer.alloc(40 * 1024, 'x')]);
    const err = new AxiosError('Request failed', 'ERR_BAD_REQUEST', undefined, undefined, {
      status: 500,
      data: stream,
    } as AxiosResponse);

    await handleProxyError({ res, err, logger, fallbackMessage: 'Failed to download job run report' });

    expect(stream.destroyed).toBe(true);
    expect(json).toHaveBeenCalledWith({ error: 'Failed to download job run report' });
  });

  it('replies 500 with the fallback message for non-Error throwables', async () => {
    const { res, status, json } = createRes();

    await handleProxyError({ res, err: 'boom', logger, fallbackMessage: 'Failed to list flows' });

    expect(status).toHaveBeenCalledWith(500);
    expect(json).toHaveBeenCalledWith({ error: 'Failed to list flows' });
  });
});

describe('query helpers', () => {
  it('queryString narrows primitives and returns undefined for objects', () => {
    expect(queryString('a')).toBe('a');
    expect(queryString(5)).toBe('5');
    expect(queryString(false)).toBe('false');
    expect(queryString(['a', 'b'])).toBe('a,b');
    expect(queryString(undefined)).toBeUndefined();
    expect(queryString({ a: 'b' })).toBeUndefined();
  });

  it('routeParam narrows a route parameter to a string', () => {
    expect(routeParam('abc')).toBe('abc');
    expect(routeParam(['first', 'second'])).toBe('first');
    expect(routeParam(undefined)).toBe('');
  });

  it('queryStringList returns every string entry', () => {
    expect(queryStringList('a')).toEqual(['a']);
    expect(queryStringList(['a', { b: 'c' }, 'd'])).toEqual(['a', 'd']);
    expect(queryStringList(undefined)).toEqual([]);
  });
});
