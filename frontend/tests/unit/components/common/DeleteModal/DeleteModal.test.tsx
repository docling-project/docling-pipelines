import { describe, it, expect, vi } from 'vitest';
import { screen, fireEvent } from '@testing-library/react';
import { renderWithProviders } from '../../../../utils/renderWithProviders';
import React from 'react';
import { DeleteModal } from '@/components/common/DeleteModal/DeleteModal';

function renderDeleteModal(props: Partial<Parameters<typeof DeleteModal>[0]> = {}) {
  const defaults = {
    open: true,
    assetType: 'Flow',
    assetName: 'My Test Flow',
    onCancel: vi.fn(),
    onDelete: vi.fn(() => Promise.resolve()),
    ...props,
  };
  return { ...renderWithProviders(React.createElement(DeleteModal, defaults)), ...defaults };
}

describe('DeleteModal', () => {
  it('renders with asset name in body text', () => {
    renderDeleteModal();
    expect(screen.getByText('My Test Flow')).toBeDefined();
  });

  it('renders the Delete asset-type heading', () => {
    renderDeleteModal();
    expect(screen.getByText('Delete Flow')).toBeDefined();
  });

  it('Cancel → onCancel called; onDelete not called', () => {
    const { onCancel, onDelete } = renderDeleteModal();
    fireEvent.click(screen.getByRole('button', { name: /cancel/i }));
    expect(onCancel).toHaveBeenCalledOnce();
    expect(onDelete).not.toHaveBeenCalled();
  });

  it('Confirm → onDelete called', async () => {
    const onDelete = vi.fn(() => Promise.resolve());
    renderDeleteModal({ onDelete });
    fireEvent.click(screen.getByRole('button', { name: /delete/i }));
    expect(onDelete).toHaveBeenCalledOnce();
  });

  it('modal hidden when open=false', () => {
    renderDeleteModal({ open: false });
    // Carbon ComposedModal hides via CSS but may still exist in DOM.
    // The modal wrapper gets aria-hidden or display:none — just confirm no Delete button is active
    const modal = document.querySelector('.cds--modal');
    // When closed the modal is either absent or not open
    expect(modal?.classList.contains('is-visible') ?? false).toBe(false);
  });
});
