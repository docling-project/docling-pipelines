/**
 * @fileoverview Sanitizer utility for return_to URL values.
 * Used to guard against open-redirect vulnerabilities.
 */

/**
 * Sanitizes a redirect path (`return_to`) value.
 * Accepts same-application relative paths starting with a single '/' (e.g., '/flows/x?a=1').
 * Rejects absolute URLs, protocol-relative paths ('//'), backslashes ('\\'), non-strings, and empty values.
 *
 * @param value - The value to sanitize.
 * @returns The sanitized path or null if unsafe/invalid.
 */
export function sanitizeReturnTo(value: unknown): string | null {
  if (typeof value !== 'string' || !value) {
    return null;
  }

  // Must start with '/' but not '//'
  if (!value.startsWith('/') || value.startsWith('//')) {
    return null;
  }

  // Must not contain backslashes or ASCII control characters
  // eslint-disable-next-line no-control-regex
  if (value.includes('\\') || /[\x00-\x1f\x7f]/.test(value)) {
    return null;
  }

  // Must not look like an absolute URL (e.g., http://, https://, or starting with letters followed by colon)
  if (/^[a-zA-Z][a-zA-Z0-9.+-]*:/.test(value)) {
    return null;
  }

  return value;
}
