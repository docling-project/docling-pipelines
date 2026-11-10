import { describe, it, expect } from 'vitest';
import { screen } from '@testing-library/react';
import { renderWithProviders } from '../../../../utils/renderWithProviders';
import { PermissionTooltip } from '@/components/common/PermissionTooltip';
import { usePermissionReason } from '@/components/common/PermissionTooltip/usePermissionReason';
import { authPreloadedState, ME } from '../../../../mocks/fixtures/permission.fixture';

function ReasonProbe({ owner }: { owner?: string | null }) {
  const { createReason, getModifyReason } = usePermissionReason();
  return (
    <>
      <span data-testid="create">{createReason ?? 'allowed'}</span>
      <span data-testid="modify">{getModifyReason(owner) ?? 'allowed'}</span>
    </>
  );
}

describe('PermissionTooltip', () => {
  it('renders children unchanged without a reason', () => {
    renderWithProviders(<PermissionTooltip reason={null}><button type="button">Go</button></PermissionTooltip>);
    expect(screen.getByRole('button', { name: 'Go' })).toBeInTheDocument();
    expect(document.querySelector('[role="tooltip"]')).toBeNull();
  });

  it('describes the control with the reason when provided', () => {
    renderWithProviders(
      <PermissionTooltip reason="Not allowed"><button type="button" disabled>Go</button></PermissionTooltip>
    );
    expect(screen.getByRole('tooltip', { hidden: true })).toHaveTextContent('Not allowed');
  });
});

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
