import { describe, it, expect, beforeEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { useRoutePreload, clearPreloadCache } from '@/hooks/useRoutePreload';

describe('useRoutePreload', () => {
  beforeEach(() => {
    clearPreloadCache();
  });

  it('returns an object with a preload function', () => {
    const { result } = renderHook(() => useRoutePreload());
    expect(typeof result.current.preload).toBe('function');
  });

  it('preload does not throw for a known path', () => {
    const { result } = renderHook(() => useRoutePreload());
    expect(() => {
      act(() => { result.current.preload('/projects'); });
    }).not.toThrow();
  });

  it('preload does not throw for an unknown path', () => {
    const { result } = renderHook(() => useRoutePreload());
    expect(() => {
      act(() => { result.current.preload('/totally-unknown-path'); });
    }).not.toThrow();
  });

  it('calling preload twice for same path is idempotent (no errors)', () => {
    const { result } = renderHook(() => useRoutePreload());
    act(() => {
      result.current.preload('/projects');
      result.current.preload('/projects');
    });
    // No assertion needed — just must not throw
  });
});
