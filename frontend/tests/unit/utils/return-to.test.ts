import { describe, it, expect } from 'vitest';
import { sanitizeReturnTo } from '@/utils/return-to';

describe('sanitizeReturnTo', () => {
  it('accepts same-application relative paths', () => {
    expect(sanitizeReturnTo('/flows/x?a=1')).toBe('/flows/x?a=1');
    expect(sanitizeReturnTo('/projects')).toBe('/projects');
    expect(sanitizeReturnTo('/')).toBe('/');
  });

  it('rejects protocol-relative paths', () => {
    expect(sanitizeReturnTo('//flows/x')).toBeNull();
    expect(sanitizeReturnTo('//google.com')).toBeNull();
  });

  it('rejects backslashes', () => {
    expect(sanitizeReturnTo('/\\flows')).toBeNull();
    expect(sanitizeReturnTo('/flows\\x')).toBeNull();
    expect(sanitizeReturnTo('\\flows')).toBeNull();
  });

  it('rejects absolute URLs', () => {
    expect(sanitizeReturnTo('http://google.com/flows/x')).toBeNull();
    expect(sanitizeReturnTo('https://localhost:3000/projects')).toBeNull();
    expect(sanitizeReturnTo('javascript:alert(1)')).toBeNull();
  });

  it('rejects non-string and empty values', () => {
    expect(sanitizeReturnTo('')).toBeNull();
    expect(sanitizeReturnTo(null)).toBeNull();
    expect(sanitizeReturnTo(undefined)).toBeNull();
    expect(sanitizeReturnTo(42)).toBeNull();
    expect(sanitizeReturnTo({})).toBeNull();
  });
});
