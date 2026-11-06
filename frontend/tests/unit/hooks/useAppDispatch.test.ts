import { describe, it, expect } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import React from 'react';
import { Provider } from 'react-redux';
import { createTestStore, buildPreloadedState } from '../../mocks/fixtures/store.fixture';
import { useAppDispatch } from '@/hooks/useAppDispatch';
import { setLoading } from '@/slices/flowSlice';

function makeWrapper(store: ReturnType<typeof createTestStore>) {
  return function Wrapper({ children }: { children: React.ReactNode }) {
    return React.createElement(Provider as any, { store }, children);
  };
}

describe('useAppDispatch', () => {
  it('returns a function', () => {
    const store = createTestStore(buildPreloadedState());
    const { result } = renderHook(() => useAppDispatch(), { wrapper: makeWrapper(store) });
    expect(typeof result.current).toBe('function');
  });

  it('dispatching an action updates store state', () => {
    const store = createTestStore(buildPreloadedState());
    const { result } = renderHook(() => useAppDispatch(), { wrapper: makeWrapper(store) });
    act(() => {
      result.current(setLoading(true));
    });
    expect(store.getState().flow.loading).toBe(true);
  });
});
