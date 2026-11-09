import { describe, it, expect } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import React from 'react';
import { Provider } from 'react-redux';
import { createTestStore, buildPreloadedState } from '../../mocks/fixtures/store.fixture';
import { useAppSelector } from '@/hooks/useAppSelector';
import { setLoading } from '@/slices/flowSlice';

function makeWrapper(store: ReturnType<typeof createTestStore>) {
  return function Wrapper({ children }: { children: React.ReactNode }) {
    return React.createElement(Provider as any, { store }, children);
  };
}

describe('useAppSelector', () => {
  it('returns the correct slice of state', () => {
    const store = createTestStore(buildPreloadedState());
    const { result } = renderHook(
      () => useAppSelector((state) => state.flow.loading),
      { wrapper: makeWrapper(store) }
    );
    expect(result.current).toBe(false);
  });

  it('re-renders when selected state changes', () => {
    const store = createTestStore(buildPreloadedState());
    const { result } = renderHook(
      () => useAppSelector((state) => state.flow.loading),
      { wrapper: makeWrapper(store) }
    );
    expect(result.current).toBe(false);
    act(() => {
      store.dispatch(setLoading(true));
    });
    expect(result.current).toBe(true);
  });
});
