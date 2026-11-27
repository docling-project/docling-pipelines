import { describe, it, expect, vi } from 'vitest';
import { screen, fireEvent, waitFor } from '@testing-library/react';
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

describe('EditDetailsModal duplicate name handling', () => {
  const DUPLICATE_MSG = 'A flow with this name already exists. Please choose a unique name.';
  const dupProps = { existingNames: ['test-pipeline-2'], duplicateNameMessage: DUPLICATE_MSG };

  const typeName = async (value: string) => {
    const nameInput = screen.getByRole('textbox', { name: /^name$/i });
    await userEvent.clear(nameInput);
    await userEvent.type(nameInput, value);
  };

  it('renaming to an existing name shows the duplicate error and blocks save', async () => {
    const onEdit = vi.fn(() => Promise.resolve());
    renderModal({ ...dupProps, onEdit });
    await typeName('test-pipeline-2');
    fireEvent.click(screen.getByRole('button', { name: /save/i }));
    expect(screen.getByText(DUPLICATE_MSG)).toBeDefined();
    expect(onEdit).not.toHaveBeenCalled();
  });

  it('duplicate check ignores case and surrounding whitespace', async () => {
    const onEdit = vi.fn(() => Promise.resolve());
    renderModal({ ...dupProps, onEdit });
    await typeName('  TEST-Pipeline-2 ');
    fireEvent.click(screen.getByRole('button', { name: /save/i }));
    expect(screen.getByText(DUPLICATE_MSG)).toBeDefined();
    expect(onEdit).not.toHaveBeenCalled();
  });

  it('shows the duplicate error on blur, before Save is clicked', async () => {
    renderModal(dupProps);
    await typeName('test-pipeline-2');
    fireEvent.blur(screen.getByRole('textbox', { name: /^name$/i }));
    expect(screen.getByText(DUPLICATE_MSG)).toBeDefined();
  });

  it('renaming to a unique name saves', async () => {
    const onEdit = vi.fn(() => Promise.resolve());
    renderModal({ ...dupProps, onEdit });
    await typeName('brand-new-name');
    fireEvent.click(screen.getByRole('button', { name: /save/i }));
    expect(screen.queryByText(DUPLICATE_MSG)).toBeNull();
    expect(onEdit).toHaveBeenCalledWith(expect.objectContaining({ name: 'brand-new-name' }));
  });

  it('saving without changing the name still works', () => {
    // existingNames excludes the entity being edited, so its own name is not a duplicate.
    const onEdit = vi.fn(() => Promise.resolve());
    renderModal({ ...dupProps, onEdit });
    fireEvent.click(screen.getByRole('button', { name: /save/i }));
    expect(onEdit).toHaveBeenCalledWith(expect.objectContaining({ name: 'My Project' }));
  });

  it('editing the name clears the duplicate error', async () => {
    renderModal(dupProps);
    await typeName('test-pipeline-2');
    fireEvent.blur(screen.getByRole('textbox', { name: /^name$/i }));
    expect(screen.getByText(DUPLICATE_MSG)).toBeDefined();
    await userEvent.type(screen.getByRole('textbox', { name: /^name$/i }), '-x');
    expect(screen.queryByText(DUPLICATE_MSG)).toBeNull();
  });

  it('a 409 from onEdit is shown as the inline duplicate error', async () => {
    const onEdit = vi.fn(() => Promise.reject({ response: { status: 409 } }));
    renderModal({ ...dupProps, onEdit });
    await typeName('stale-list-name');
    fireEvent.click(screen.getByRole('button', { name: /save/i }));
    expect(await screen.findByText(DUPLICATE_MSG)).toBeDefined();
  });

  it('a non-409 failure does not show the duplicate error', async () => {
    const onEdit = vi.fn(() => Promise.reject({ response: { status: 500 } }));
    renderModal({ ...dupProps, onEdit });
    await typeName('another-name');
    fireEvent.click(screen.getByRole('button', { name: /save/i }));
    await waitFor(() => { expect(onEdit).toHaveBeenCalled(); });
    expect(screen.queryByText(DUPLICATE_MSG)).toBeNull();
  });

  it('does no duplicate checking when duplicateNameMessage is not provided (e.g. project edit)', async () => {
    const onEdit = vi.fn(() => Promise.resolve());
    renderModal({ existingNames: ['test-pipeline-2'], onEdit });
    await typeName('test-pipeline-2');
    fireEvent.click(screen.getByRole('button', { name: /save/i }));
    expect(onEdit).toHaveBeenCalled();
  });
});
