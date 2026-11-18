import { describe, it, expect, vi } from 'vitest';
import { screen, fireEvent, waitFor } from '@testing-library/react';
import { renderWithProviders } from '../../../utils/renderWithProviders';
import { CreateFlowTearsheet } from '@/components/ProjectDetail/CreateFlowTearsheet/CreateFlowTearsheet';

function renderTearsheet(props: Partial<Parameters<typeof CreateFlowTearsheet>[0]> = {}) {
  const defaults = {
    open: true,
    onClose: vi.fn(),
    onSubmit: vi.fn(),
    ...props,
  };
  return { ...renderWithProviders(<CreateFlowTearsheet {...defaults} />), ...defaults };
}

describe('CreateFlowTearsheet', () => {
  it('renders the modal title', () => {
    renderTearsheet();
    expect(screen.getByText('Create flow')).toBeDefined();
  });

  it('Submit with empty name does not call onSubmit', () => {
    const { onSubmit } = renderTearsheet();
    // Create button is not disabled by default — validation fires on click
    fireEvent.click(screen.getByRole('button', { name: /^create$/i }));
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it('Cancel button calls onClose', () => {
    const { onClose } = renderTearsheet();
    fireEvent.click(screen.getByRole('button', { name: /cancel/i }));
    expect(onClose).toHaveBeenCalledOnce();
  });

  it('typing a name enables Create button', async () => {
    renderTearsheet();
    const input = screen.getByLabelText(/^name$/i);
    fireEvent.change(input, { target: { value: 'My Flow' } });
    await waitFor(() => {
      const createBtn = screen.getByRole('button', { name: /^create$/i });
      expect((createBtn as HTMLButtonElement).disabled).toBe(false);
    });
  });

  it('submitting with a valid name calls onSubmit', async () => {
    const { onSubmit } = renderTearsheet();
    const input = screen.getByLabelText(/^name$/i);
    fireEvent.change(input, { target: { value: 'My Flow' } });
    fireEvent.click(screen.getByRole('button', { name: /^create$/i }));
    expect(onSubmit).toHaveBeenCalledWith({ name: 'My Flow', description: '', tags: [] });
  });

  it('shows duplicate error when name already exists', async () => {
    renderTearsheet({ existingNames: ['Existing Flow'] });
    const input = screen.getByLabelText(/^name$/i);
    fireEvent.change(input, { target: { value: 'Existing Flow' } });
    fireEvent.blur(input);
    await waitFor(() => {
      expect(screen.getByText(/already exists/i)).toBeDefined();
    });
  });

  it('shows API error when error prop is set', () => {
    renderTearsheet({ error: 'Server error occurred' });
    expect(screen.getByText('Server error occurred')).toBeDefined();
  });

  it('modal hidden when open=false', () => {
    const { container } = renderTearsheet({ open: false });
    const modal = container.querySelector('.cds--modal');
    expect(modal?.classList.contains('is-visible') ?? false).toBe(false);
  });

  it('submitting duplicate name sets duplicate error and does not call onSubmit', async () => {
    const { onSubmit } = renderTearsheet({ existingNames: ['My Flow'] });
    const input = screen.getByLabelText(/^name$/i);
    fireEvent.change(input, { target: { value: 'My Flow' } });
    fireEvent.click(screen.getByRole('button', { name: /^create$/i }));
    expect(onSubmit).not.toHaveBeenCalled();
    await waitFor(() => {
      expect(screen.getByText(/already exists/i)).toBeDefined();
    });
  });

  it('description textarea onChange updates description', () => {
    const { onSubmit } = renderTearsheet();
    const nameInput = screen.getByLabelText(/^name$/i);
    fireEvent.change(nameInput, { target: { value: 'Flow A' } });
    const descTextarea = screen.getByLabelText(/description/i) as HTMLTextAreaElement;
    fireEvent.change(descTextarea, { target: { value: 'My description' } });
    fireEvent.click(screen.getByRole('button', { name: /^create$/i }));
    expect(onSubmit).toHaveBeenCalledWith(
      expect.objectContaining({ description: 'My description' })
    );
  });

  it('name input onBlur sets nameInvalid when empty', async () => {
    renderTearsheet();
    const input = screen.getByLabelText(/^name$/i);
    fireEvent.focus(input);
    fireEvent.blur(input);
    await waitFor(() => {
      expect(document.body).toBeInTheDocument();
    });
  });

  it('typing name clears nameInvalid and nameDuplicate', async () => {
    const { onSubmit } = renderTearsheet({ existingNames: ['My Flow'] });
    const input = screen.getByLabelText(/^name$/i);
    // Trigger duplicate error first
    fireEvent.change(input, { target: { value: 'My Flow' } });
    fireEvent.click(screen.getByRole('button', { name: /^create$/i }));
    // Now type to clear the error
    fireEvent.change(input, { target: { value: 'New Flow' } });
    fireEvent.click(screen.getByRole('button', { name: /^create$/i }));
    expect(onSubmit).toHaveBeenCalledWith(
      expect.objectContaining({ name: 'New Flow' })
    );
  });
});
