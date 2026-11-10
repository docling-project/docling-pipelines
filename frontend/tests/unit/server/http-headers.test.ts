import { describe, it, expect } from 'vitest';
import { BODY_HEADERS, NO_BODY_HEADERS, buildForwardHeaders } from '../../../server/controllers/http-headers';

const asReq = (headers: Record<string, string | string[]>) => ({ headers });

describe('buildForwardHeaders', () => {
  it('forwards the four credential and context headers', () => {
    const headers = buildForwardHeaders(
      asReq({
        cookie: 'docpipe_access_token=abc',
        authorization: 'Bearer token',
        'x-requested-with': 'XMLHttpRequest',
        'x-transaction-id': 'tx-1',
      }),
      NO_BODY_HEADERS
    );

    expect(headers).toEqual({
      Accept: 'application/json',
      Cookie: 'docpipe_access_token=abc',
      Authorization: 'Bearer token',
      'X-Requested-With': 'XMLHttpRequest',
      'X-Transaction-ID': 'tx-1',
    });
  });

  it('drops X-Forwarded-* and any other browser header', () => {
    const headers = buildForwardHeaders(
      asReq({
        'x-forwarded-for': '10.0.0.1',
        'x-forwarded-proto': 'https',
        host: 'example.com',
        'user-agent': 'test',
      }),
      BODY_HEADERS
    );

    expect(headers).toEqual(BODY_HEADERS);
  });

  it('omits headers that are not present', () => {
    expect(buildForwardHeaders(asReq({ cookie: 'a=b' }), NO_BODY_HEADERS)).toEqual({
      Accept: 'application/json',
      Cookie: 'a=b',
    });
  });

  it('keeps the base Accept header and does not mutate the base', () => {
    const base = { Accept: 'text/csv' };
    const headers = buildForwardHeaders(asReq({ cookie: 'a=b' }), base);

    expect(headers.Accept).toBe('text/csv');
    expect(base).toEqual({ Accept: 'text/csv' });
  });

  it('joins repeated header values', () => {
    const headers = buildForwardHeaders(asReq({ cookie: ['a=1', 'b=2'] }), NO_BODY_HEADERS);

    expect(headers.Cookie).toBe('a=1, b=2');
  });
});
