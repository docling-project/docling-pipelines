import { describe, it, expect, vi } from 'vitest';
import { screen, fireEvent, waitFor } from '@testing-library/react';
import { renderWithProviders } from '../../../../utils/renderWithProviders';
import { CreateProjectTearsheet } from '@/components/common/CreateProjectTearsheet/CreateProjectTearsheet';

function renderTearsheet(
  props: Partial<Parameters<typeof CreateProjectTearsheet>[0]> & { preloadedState?: object } = {}
) {
  const { preloadedState, ...componentProps } = props;
  const defaults = {
    open: true,
    onClose: vi.fn(),
    onSubmit: vi.fn(() => Promise.resolve()),
    ...componentProps,
  };
  return {
    ...renderWithProviders(<CreateProjectTearsheet {...defaults} />, preloadedState ? { preloadedState } as any : {}),
    ...defaults,
  };
}

describe('CreateProjectTearsheet', () => {
  it('renders the modal title and step 1 heading on mount', () => {
    renderTearsheet();
    expect(screen.getByText('Create project and add flow')).toBeDefined();
    expect(screen.getByText('Define project details')).toBeDefined();
  });

  it('Next button disabled when name is empty or only whitespace', () => {
    renderTearsheet();
    const nextButton = screen.getByRole('button', { name: /^next$/i });
    expect((nextButton as HTMLButtonElement).disabled).toBe(true);

    const input = screen.getByLabelText(/^name$/i);
    fireEvent.change(input, { target: { value: '   ' } });
    expect((nextButton as HTMLButtonElement).disabled).toBe(true);
  });

  it('Cancel button calls onClose and resets form state', () => {
    const { onClose } = renderTearsheet();
    const input = screen.getByLabelText(/^name$/i);
    fireEvent.change(input, { target: { value: 'Temp Project' } });
    fireEvent.click(screen.getByRole('button', { name: /^cancel$/i }));
    expect(onClose).toHaveBeenCalledOnce();
  });

  it('typing name, description, and tags in step 1 updates fields correctly', async () => {
    renderTearsheet();
    const nameInput = screen.getByLabelText(/^name$/i);
    fireEvent.change(nameInput, { target: { value: 'My Project' } });

    const descInput = screen.getByLabelText(/description/i);
    fireEvent.change(descInput, { target: { value: 'Project description here' } });
    expect((descInput as HTMLTextAreaElement).value).toBe('Project description here');

    const tagsInput = screen.getByPlaceholderText('Add tags');
    fireEvent.change(tagsInput, { target: { value: 'tag1' } });
    fireEvent.keyDown(tagsInput, { key: 'Enter' });

    await waitFor(() => {
      expect(screen.getByText('tag1')).toBeDefined();
    });
  });

  it('shows duplicate-name error on blur when project name already exists', async () => {
    renderTearsheet({
      preloadedState: {
        projects: {
          loading: false,
          error: null,
          selectedProjectId: null,
          items: {
            p1: { id: 'p1', name: 'Existing Project', description: '', tags: [], flowCount: 0, createdOn: '', modifiedOn: '' },
          },
        },
      } as any,
    });
    const input = screen.getByLabelText(/^name$/i);
    fireEvent.change(input, { target: { value: 'Existing Project' } });
    fireEvent.blur(input);
    await waitFor(() => {
      expect(screen.getByText(/already exists/i)).toBeDefined();
    });

    const nextButton = screen.getByRole('button', { name: /^next$/i });
    expect((nextButton as HTMLButtonElement).disabled).toBe(true);
  });

  it('handleNameBlur with non-duplicate name does not trigger duplicate error', async () => {
    renderTearsheet({
      preloadedState: {
        projects: {
          loading: false,
          error: null,
          selectedProjectId: null,
          items: {
            p1: { id: 'p1', name: 'Existing Project', description: '', tags: [], flowCount: 0, createdOn: '', modifiedOn: '' },
          },
        },
      } as any,
    });
    const input = screen.getByLabelText(/^name$/i);
    fireEvent.change(input, { target: { value: 'Unique Name' } });
    fireEvent.blur(input);
    expect(screen.queryByText(/already exists/i)).toBeNull();
  });

  it('handleNameBlur with empty name does not trigger duplicate error', () => {
    renderTearsheet();
    const input = screen.getByLabelText(/^name$/i);
    fireEvent.blur(input);
    expect(screen.queryByText(/already exists/i)).toBeNull();
  });

  it('clicking Next advances to step 2 and allows entering flow details', async () => {
    renderTearsheet();
    const nameInput = screen.getByLabelText(/^name$/i);
    fireEvent.change(nameInput, { target: { value: 'My Project' } });

    const nextButton = screen.getByRole('button', { name: /^next$/i });
    fireEvent.click(nextButton);

    await waitFor(() => {
      expect(screen.getByText('Define flow details (optional)')).toBeDefined();
    });

    // Enter flow fields
    const flowNameInput = screen.getByLabelText(/^name$/i);
    fireEvent.change(flowNameInput, { target: { value: 'My Flow' } });
    expect((flowNameInput as HTMLInputElement).value).toBe('My Flow');

    const flowDescInput = screen.getByLabelText(/description/i);
    fireEvent.change(flowDescInput, { target: { value: 'Flow description' } });
    expect((flowDescInput as HTMLTextAreaElement).value).toBe('Flow description');

    const flowTagsInput = screen.getByPlaceholderText('Add tags');
    fireEvent.change(flowTagsInput, { target: { value: 'flowtag' } });
    fireEvent.keyDown(flowTagsInput, { key: 'Enter' });

    await waitFor(() => {
      expect(screen.getByText('flowtag')).toBeDefined();
    });
  });

  it('clicking Back from step 2 returns to step 1 preserving values', async () => {
    renderTearsheet();
    const nameInput = screen.getByLabelText(/^name$/i);
    fireEvent.change(nameInput, { target: { value: 'My Project' } });
    fireEvent.click(screen.getByRole('button', { name: /^next$/i }));

    await waitFor(() => {
      expect(screen.getByText('Define flow details (optional)')).toBeDefined();
    });

    fireEvent.click(screen.getByRole('button', { name: /^back$/i }));

    await waitFor(() => {
      expect(screen.getByText('Define project details')).toBeDefined();
      expect((screen.getByLabelText(/^name$/i) as HTMLInputElement).value).toBe('My Project');
    });
  });

  it('submitting successfully calls onSubmit with project and flow values, then closes', async () => {
    const onSubmit = vi.fn(() => Promise.resolve());
    const onClose = vi.fn();
    renderTearsheet({ onSubmit, onClose });

    // Step 1
    fireEvent.change(screen.getByLabelText(/^name$/i), { target: { value: 'Full Project' } });
    fireEvent.change(screen.getByLabelText(/description/i), { target: { value: 'Full Desc' } });
    fireEvent.click(screen.getByRole('button', { name: /^next$/i }));

    // Step 2
    await waitFor(() => {
      expect(screen.getByText('Define flow details (optional)')).toBeDefined();
    });
    fireEvent.change(screen.getByLabelText(/^name$/i), { target: { value: 'Full Flow' } });
    fireEvent.change(screen.getByLabelText(/description/i), { target: { value: 'Flow Desc' } });

    const createButton = screen.getByRole('button', { name: /^create$/i });
    fireEvent.click(createButton);

    await waitFor(() => {
      expect(onSubmit).toHaveBeenCalledWith(
        { name: 'Full Project', description: 'Full Desc', tags: [] },
        { flowName: 'Full Flow', flowDescription: 'Flow Desc', flowTags: [] }
      );
      expect(onClose).toHaveBeenCalledOnce();
    });
  });

  it('submitting failure keeps modal open and stops submitting spinner', async () => {
    let rejectPromise: (reason?: any) => void = () => {};
    const onSubmit = vi.fn(
      () =>
        new Promise<void>((_, reject) => {
          rejectPromise = reject;
        })
    );
    const onClose = vi.fn();
    renderTearsheet({ onSubmit, onClose });

    fireEvent.change(screen.getByLabelText(/^name$/i), { target: { value: 'My Project' } });
    fireEvent.click(screen.getByRole('button', { name: /^next$/i }));

    await waitFor(() => {
      expect(screen.getByText('Define flow details (optional)')).toBeDefined();
    });

    const createButton = screen.getByRole('button', { name: /^create$/i });
    fireEvent.click(createButton);

    // submitting state active
    await waitFor(() => {
      expect(screen.getByText('Creating...')).toBeDefined();
    });

    // Reject the promise
    rejectPromise(new Error('Network error'));

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /^create$/i })).toBeDefined();
      expect(onClose).not.toHaveBeenCalled();
    });
  });

  it('shows validation error state when name is empty', async () => {
    renderTearsheet();
    const input = screen.getByLabelText(/^name$/i);
    const nextButton = screen.getByRole('button', { name: /^next$/i });
    expect((nextButton as HTMLButtonElement).disabled).toBe(true);

    fireEvent.change(input, { target: { value: 'Temp' } });
    expect((nextButton as HTMLButtonElement).disabled).toBe(false);

    fireEvent.change(input, { target: { value: '' } });
    expect((nextButton as HTMLButtonElement).disabled).toBe(true);
  });

  it('clicking Next fallback validation triggers when name is duplicate', async () => {
    renderTearsheet({
      preloadedState: {
        projects: {
          loading: false,
          error: null,
          selectedProjectId: null,
          items: {
            p1: { id: 'p1', name: 'Existing Project', description: '', tags: [], flowCount: 0, createdOn: '', modifiedOn: '' },
          },
        },
      } as any,
    });
    const input = screen.getByLabelText(/^name$/i);
    fireEvent.change(input, { target: { value: 'Existing Project' } });
    const nextButton = screen.getByRole('button', { name: /^next$/i });
    nextButton.removeAttribute('disabled');
    fireEvent.click(nextButton);
    await waitFor(() => {
      expect(screen.getByText(/already exists/i)).toBeDefined();
    });
  });

  it('modal hidden when open=false', () => {
    const { container } = renderTearsheet({ open: false });
    const modal = container.querySelector('.cds--modal');
    expect(modal?.classList.contains('is-visible') ?? false).toBe(false);
  });
});
