import { describe, it, expect, vi } from 'vitest';
import { screen, fireEvent } from '@testing-library/react';
import { renderWithProviders } from '../../../utils/renderWithProviders';
import { TileContent } from '@/components/TileContent/TileContent';

describe('TileContent disabled state', () => {
  it('keeps the action button enabled by default', () => {
    const onAction = vi.fn();
    renderWithProviders(<TileContent label="L" title="T" subtitle="S" buttonLabel="Start" onAction={onAction} />);
    const button = screen.getByRole('button', { name: 'Start' });
    expect(button).not.toBeDisabled();
    fireEvent.click(button);
    expect(onAction).toHaveBeenCalledTimes(1);
  });

  it('disables the action button and explains why', () => {
    const onAction = vi.fn();
    renderWithProviders(
      <TileContent label="L" title="T" subtitle="S" buttonLabel="Start" onAction={onAction} disabled disabledReason="Not allowed" />
    );
    expect(screen.getByRole('button', { name: 'Start' })).toBeDisabled();
    expect(screen.getByText('Not allowed', { selector: '[role="tooltip"] *' })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Start' }));
    expect(onAction).not.toHaveBeenCalled();
  });

  it('does not disable a link tile', () => {
    renderWithProviders(
      <TileContent label="L" title="T" subtitle="S" buttonLabel="Docs" href="https://example.com" disabled disabledReason="x" />
    );
    expect(screen.getByText('Docs').closest('a')).toHaveAttribute('href', 'https://example.com');
  });
});
