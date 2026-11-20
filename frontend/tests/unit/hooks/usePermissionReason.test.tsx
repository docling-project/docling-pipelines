import React from 'react';
import { describe, it, expect } from 'vitest';
import { screen } from '@testing-library/react';
import { renderWithProviders } from '../../utils/renderWithProviders';
import { usePermissionReason } from '@/hooks/usePermissionReason';
import { authPreloadedState, ME } from '../../mocks/fixtures/permission.fixture';

function ReasonProbe({ owner }: { owner?: string | null }): React.JSX.Element {
  const { createReason, getModifyReason } = usePermissionReason();
  return (
    <>
      <span data-testid="create">{createReason ?? 'allowed'}</span>
      <span data-testid="modify">{getModifyReason(owner) ?? 'allowed'}</span>
    </>
  );
}

describe('usePermissionReason', () => {
  it('returns the editor-role message for a viewer', () => {
    renderWithProviders(<ReasonProbe owner={ME} />, { preloadedState: authPreloadedState('viewer') });
    expect(screen.getByTestId('create')).toHaveTextContent('You need the editor role to do this');
    expect(screen.getByTestId('modify')).toHaveTextContent('You need the editor role to do this');
  });

  it('returns the ownership message for an editor on a foreign asset', () => {
    renderWithProviders(<ReasonProbe owner="other" />, { preloadedState: authPreloadedState('editor') });
    expect(screen.getByTestId('create')).toHaveTextContent('allowed');
    expect(screen.getByTestId('modify')).toHaveTextContent('Only the owner or an administrator can change this');
  });

  it('allows an admin on a foreign asset', () => {
    renderWithProviders(<ReasonProbe owner="other" />, { preloadedState: authPreloadedState('admin') });
    expect(screen.getByTestId('modify')).toHaveTextContent('allowed');
  });
});
