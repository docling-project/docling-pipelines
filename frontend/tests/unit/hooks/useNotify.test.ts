import { describe, it, expect } from 'vitest';
import { act } from '@testing-library/react';
import { renderHook } from '@testing-library/react';
import React from 'react';
import { Provider } from 'react-redux';
import { createTestStore, buildPreloadedState } from '../../mocks/fixtures/store.fixture';
import { useNotify } from '@/hooks/useNotify';

function makeWrapper(store: ReturnType<typeof createTestStore>) {
  return function Wrapper({ children }: { children: React.ReactNode }) {
    return React.createElement(Provider as any, { store }, children);
  };
}

describe('useNotify', () => {
  it('success dispatches addNotification with kind "success"', () => {
    const store = createTestStore(buildPreloadedState());
    const { result } = renderHook(() => useNotify(), { wrapper: makeWrapper(store) });

    act(() => {
      result.current.success('Flow saved');
    });

    const active = store.getState().notifications.active;
    expect(active).toHaveLength(1);
    expect(active[0]?.kind).toBe('success');
    expect(active[0]?.title).toBe('Flow saved');
  });

  it('error dispatches addNotification with kind "error" and dismissAfter: 0', () => {
    const store = createTestStore(buildPreloadedState());
    const { result } = renderHook(() => useNotify(), { wrapper: makeWrapper(store) });

    act(() => {
      result.current.error('Failed to save');
    });

    const active = store.getState().notifications.active;
    expect(active[0]?.kind).toBe('error');
    expect(active[0]?.dismissAfter).toBe(0);
  });

  it('info dispatches addNotification with kind "info"', () => {
    const store = createTestStore(buildPreloadedState());
    const { result } = renderHook(() => useNotify(), { wrapper: makeWrapper(store) });

    act(() => {
      result.current.info('Processing');
    });

    expect(store.getState().notifications.active[0]?.kind).toBe('info');
  });
});
