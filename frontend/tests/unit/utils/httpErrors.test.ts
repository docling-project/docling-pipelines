import { describe, it, expect } from 'vitest';
import { isConflictError } from '@/utils/httpErrors';

describe('isConflictError', () => {
  it('is true for a 409 response', () => {
    expect(isConflictError({ response: { status: 409 } })).toBe(true);
  });

  it('is false for other statuses', () => {
    expect(isConflictError({ response: { status: 500 } })).toBe(false);
    expect(isConflictError({ response: { status: 404 } })).toBe(false);
  });

  it('is false for errors without a response, null and undefined', () => {
    expect(isConflictError(new Error('network'))).toBe(false);
    expect(isConflictError(null)).toBe(false);
    expect(isConflictError(undefined)).toBe(false);
  });
});
