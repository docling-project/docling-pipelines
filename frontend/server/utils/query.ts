/**
 * Express types `req.query` values as `string | ParsedQs | (string | ParsedQs)[] | undefined`.
 * These helpers narrow them to plain strings for building upstream query strings.
 */

/** Returns a string for string/number/boolean/array-of-those values; `undefined` otherwise. */
export const queryString = (value: unknown): string | undefined => {
  if (typeof value === 'string') return value;
  if (typeof value === 'number' || typeof value === 'boolean') return String(value);
  if (Array.isArray(value)) return value.filter((item) => typeof item === 'string').join(',');
  return undefined;
};

/** Returns every string entry of a repeatable query param (`?tag=a&tag=b`). */
export const queryStringList = (value: unknown): string[] => {
  if (typeof value === 'string') return [value];
  if (Array.isArray(value)) return value.filter((item): item is string => typeof item === 'string');
  return [];
};
