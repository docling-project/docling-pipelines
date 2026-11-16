import { describe, it, expect, beforeEach } from 'vitest';
import { isValidTheme, getStoredTheme, saveTheme, DEFAULT_THEME, THEME_STORAGE_KEY } from '@/config/theme';

describe('isValidTheme', () => {
  it('returns true for g10 (light)', () => {
    expect(isValidTheme('g10')).toBe(true);
  });

  it('returns true for g100 (dark)', () => {
    expect(isValidTheme('g100')).toBe(true);
  });

  it('returns false for unknown theme', () => {
    expect(isValidTheme('unknown')).toBe(false);
  });

  it('returns false for empty string', () => {
    expect(isValidTheme('')).toBe(false);
  });
});

describe('getStoredTheme', () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it('returns stored theme when valid', () => {
    localStorage.setItem(THEME_STORAGE_KEY, 'g10');
    expect(getStoredTheme()).toBe('g10');
  });

  it('returns DEFAULT_THEME when stored value is invalid', () => {
    localStorage.setItem(THEME_STORAGE_KEY, 'invalid-theme');
    expect(getStoredTheme()).toBe(DEFAULT_THEME);
  });

  it('returns DEFAULT_THEME when localStorage is empty', () => {
    expect(getStoredTheme()).toBe(DEFAULT_THEME);
  });
});

describe('saveTheme', () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it('stores the theme in localStorage', () => {
    saveTheme('g10');
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe('g10');
  });
});
