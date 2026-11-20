import { describe, it, expect } from 'vitest';
import { screen } from '@testing-library/react';
import { renderWithProviders } from '../../../../utils/renderWithProviders';
import { PermissionTooltip } from '@/components/common/PermissionTooltip';

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
