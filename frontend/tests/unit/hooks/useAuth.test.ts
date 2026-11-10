import { describe, it, expect } from 'vitest';
import React from 'react';
import { renderHook } from '@testing-library/react';
import { Provider } from 'react-redux';
import { useAuth } from '@/hooks/useAuth';
import { authStateFixture, buildPreloadedState, createTestStore } from '../../mocks/fixtures/store.fixture';
import type { AuthState } from '@/types';

function renderWithState(auth?: AuthState) {
  const store = createTestStore(buildPreloadedState(auth ? { auth } : undefined));
  const wrapper = ({ children }: { children: React.ReactNode }) =>
    React.createElement(Provider, { store, children });
  return renderHook(() => useAuth(), { wrapper });
}

const renderAuth = renderWithState;

describe('useAuth', () => {
  it('default test state is authenticated, auth disabled, admin-equivalent', () => {
    const { result } = renderWithState();
    expect(result.current.isAuthenticated).toBe(true);
    expect(result.current.isLoading).toBe(false);
    expect(result.current.authEnabled).toBe(false);
    expect(result.current.canAdmin).toBe(true);
    expect(result.current.canModifyAsset('anyone')).toBe(true);
  });

  it('viewer cannot edit, administer or modify any asset', () => {
    const { result } = renderAuth(authStateFixture({ role: 'viewer', username: 'vic' }));
    expect(result.current.isAuthenticated).toBe(true);
    expect(result.current.canEdit).toBe(false);
    expect(result.current.canAdmin).toBe(false);
    expect(result.current.canModifyAsset('vic')).toBe(false);
    expect(result.current.canModifyAsset(null)).toBe(false);
  });

  describe('editor', () => {
    const render = () => renderAuth(authStateFixture({ role: 'editor', username: 'eve' })).result;

    it('can edit but not administer', () => {
      const result = render();
      expect(result.current.canEdit).toBe(true);
      expect(result.current.canAdmin).toBe(false);
    });

    it('can modify own assets', () => {
      expect(render().current.canModifyAsset('eve')).toBe(true);
    });

    it('cannot modify foreign assets', () => {
      expect(render().current.canModifyAsset('someone-else')).toBe(false);
    });

    it('can modify ownerless assets', () => {
      const result = render();
      expect(result.current.canModifyAsset(null)).toBe(true);
      expect(result.current.canModifyAsset(undefined)).toBe(true);
      expect(result.current.canModifyAsset('')).toBe(true);
    });
  });

  it('admin can edit, administer and modify any asset', () => {
    const { result } = renderAuth(authStateFixture({ role: 'admin', username: 'ada' }));
    expect(result.current.canEdit).toBe(true);
    expect(result.current.canAdmin).toBe(true);
    expect(result.current.canModifyAsset('someone-else')).toBe(true);
    expect(result.current.canModifyAsset(null)).toBe(true);
  });

  it.each(['idle', 'loading'] as const)('isLoading is true while status is %s', (status) => {
    const { result } = renderAuth(authStateFixture({ overrides: { status, user: null } }));
    expect(result.current.isLoading).toBe(true);
    expect(result.current.isAuthenticated).toBe(false);
  });

  it('unauthenticated is neither loading nor authenticated', () => {
    const { result } = renderAuth(authStateFixture({ overrides: { status: 'unauthenticated', user: null } }));
    expect(result.current.isLoading).toBe(false);
    expect(result.current.isAuthenticated).toBe(false);
    expect(result.current.canEdit).toBe(false);
    expect(result.current.user).toBeNull();
  });
});
