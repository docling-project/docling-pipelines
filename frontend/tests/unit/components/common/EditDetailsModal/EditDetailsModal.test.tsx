import { describe, it, expect, vi } from 'vitest';
import { screen, fireEvent } from '@testing-library/react';
import { renderWithProviders } from '../../../../utils/renderWithProviders';
import userEvent from '@testing-library/user-event';
import React from 'react';
import { EditDetailsModal } from '@/components/common/EditDetailsModal/EditDetailsModal';

function renderModal(props: Partial<Parameters<typeof EditDetailsModal>[0]> = {}) {
  const defaults = {
    open: true,
    title: 'Edit project details',
    initialValues: { name: 'My Project', description: 'A description', tags: ['tag1'] },
    onCancel: vi.fn(),
    onEdit: vi.fn(() => Promise.resolve()),
    ...props,
  };
  return { ...renderWithProviders(React.createElement(EditDetailsModal, defaults)), ...defaults };
}

describe('EditDetailsModal', () => {
  it('pre-fills name, description, tags from props', () => {
    renderModal();
    const nameInput = screen.getByRole('textbox', { name: /name/i });
    expect((nameInput as HTMLInputElement).value).toBe('My Project');
  });

  it('editing name and saving calls onEdit with updated values', async () => {
    const onEdit = vi.fn(() => Promise.resolve());
    renderModal({ onEdit });
    const nameInput = screen.getByRole('textbox', { name: /^name$/i });
    await userEvent.clear(nameInput);
    await userEvent.type(nameInput, 'New Name');
    fireEvent.click(screen.getByRole('button', { name: /save/i }));
    expect(onEdit).toHaveBeenCalledWith(
      expect.objectContaining({ name: 'New Name' })
    );
  });

  it('empty name → does not call onEdit (validation blocks)', async () => {
    const onEdit = vi.fn(() => Promise.resolve());
    renderModal({ onEdit });
    const nameInput = screen.getByRole('textbox', { name: /^name$/i });
    await userEvent.clear(nameInput);
    fireEvent.click(screen.getByRole('button', { name: /save/i }));
    expect(onEdit).not.toHaveBeenCalled();
  });

  it('Cancel → onCancel called', () => {
    const { onCancel } = renderModal();
    fireEvent.click(screen.getByRole('button', { name: /cancel/i }));
    expect(onCancel).toHaveBeenCalledOnce();
  });
});
