import type { Request } from 'express';

export const BODY_HEADERS = {
  Accept: 'application/json',
  'Content-Type': 'application/json',
};

export const NO_BODY_HEADERS = {
  Accept: 'application/json',
};

// Browser headers relayed to the REST API. Anything else, notably
// X-Forwarded-For and X-Forwarded-Proto, is deliberately dropped.
const FORWARDED_REQUEST_HEADERS = ['Cookie', 'Authorization', 'X-Requested-With', 'X-Transaction-ID'] as const;

/**
 * Build the upstream header set: `base` plus the credential and context
 * headers from the browser request, when present.
 */
export const buildForwardHeaders = (
  req: Pick<Request, 'headers'>,
  base: Record<string, string>
): Record<string, string> => {
  const headers: Record<string, string> = { ...base };

  FORWARDED_REQUEST_HEADERS.forEach((name) => {
    const value = req.headers?.[name.toLowerCase()];
    if (value === undefined) return;
    headers[name] = Array.isArray(value) ? value.join(', ') : value;
  });

  return headers;
};
