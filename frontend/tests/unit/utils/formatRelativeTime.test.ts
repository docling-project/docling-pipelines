import { describe, it, expect } from 'vitest';
import { formatRelativeTime } from '@/utils/formatRelativeTime';

function msAgo(ms: number): string {
  return new Date(Date.now() - ms).toISOString();
}

describe('formatRelativeTime', () => {
  it('returns empty string for empty input', () => {
    expect(formatRelativeTime('')).toBe('');
  });

  it('returns empty string for invalid date', () => {
    expect(formatRelativeTime('not-a-date')).toBe('');
  });

  it('returns "Just now" for < 60 seconds ago', () => {
    expect(formatRelativeTime(msAgo(30_000))).toBe('Just now');
  });

  it('returns "X min ago" for ~5 minutes ago', () => {
    expect(formatRelativeTime(msAgo(5 * 60 * 1000))).toBe('5 min ago');
  });

  it('returns "X h ago" for ~2 hours ago', () => {
    expect(formatRelativeTime(msAgo(2 * 60 * 60 * 1000))).toBe('2 h ago');
  });

  it('returns "X d ago" for ~3 days ago', () => {
    expect(formatRelativeTime(msAgo(3 * 24 * 60 * 60 * 1000))).toBe('3 d ago');
  });

  it('returns "X mo ago" for ~2 months ago', () => {
    expect(formatRelativeTime(msAgo(60 * 24 * 60 * 60 * 1000))).toBe('2 mo ago');
  });

  it('returns "X y ago" for ~2 years ago', () => {
    expect(formatRelativeTime(msAgo(2 * 365 * 24 * 60 * 60 * 1000))).toBe('2 y ago');
  });
});
