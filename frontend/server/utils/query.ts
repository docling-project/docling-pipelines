/**
 * Express types `req.query` values as `string | ParsedQs | (string | ParsedQs)[] | undefined`.
 * These helpers only narrow those types. They do not encode anything: pass their
 * results to `proxyRequest` (`query` / `path`), which does the encoding.
 *
 * Pick the helper by the shape the backend expects:
 *  - `queryString`      -> one value        (`?limit=10`)
 *  - `queryStringList`  -> repeated keys    (`?tags=a&tags=b`)
 */

/**
 * Narrows a query value to ONE string, for parameters the backend reads as a single value.
 * Numbers and booleans are stringified; an array is joined with commas (`['a','b']` -> `'a,b'`),
 * which is NOT the repeated-key form (`?k=a&k=b`) that list parameters need. For those use
 * `queryStringList`. Returns `undefined` for anything else.
 */
export const queryString = (value: unknown): string | undefined => {
  if (typeof value === 'string') return value;
  if (typeof value === 'number' || typeof value === 'boolean') return String(value);
  if (Array.isArray(value)) return value.filter((item) => typeof item === 'string').join(',');
  return undefined;
};

/**
 * Narrows an Express route parameter (`string | string[]`) to a string.
 * Arrays only occur for wildcard routes; the first entry is used.
 * The result is still untrusted input: `proxyRequest` encodes it as a path segment.
 */
export const routeParam = (value: string | string[] | undefined): string => {
  const first = Array.isArray(value) ? value[0] : value;
  return first ?? '';
};

/**
 * Narrows a query value to a LIST of strings, for parameters the backend reads as repeated keys
 * (`?tags=a&tags=b`, e.g. FastAPI `list[str]`). Pass the result as an array in `proxyRequest`'s
 * `query`, which sends one key per entry. A single value becomes a one-item list; anything
 * that is not a string is dropped.
 */
export const queryStringList = (value: unknown): string[] => {
  if (typeof value === 'string') return [value];
  if (Array.isArray(value)) return value.filter((item): item is string => typeof item === 'string');
  return [];
};
