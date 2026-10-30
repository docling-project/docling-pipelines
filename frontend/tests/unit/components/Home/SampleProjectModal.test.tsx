import { describe, it, expect, vi, afterEach } from 'vitest';
import { screen, act } from '@testing-library/react';
import { renderWithProviders } from '../../../utils/renderWithProviders';
import { SampleProjectModal } from '@/components/Home/SampleProjectModal/SampleProjectModal';

// MSW intercepts the API calls; we just verify mounting/rendering behaviour.

describe('SampleProjectModal', () => {
  afterEach(async () => {
    // Flush all pending async microtasks (runSetup promises, Redux dispatches,
    // logger console.log calls) so none leak into the worker teardown and cause
    // "Closing rpc while onUserConsoleLog was pending" on Jenkins.
    await act(async () => {
      await new Promise((r) => setTimeout(r, 0));
    });
  });

  it('renders without crashing when closed', () => {
    const { container } = renderWithProviders(
      <SampleProjectModal open={false} onClose={vi.fn()} onSuccess={vi.fn()} />
    );
    expect(container).toBeTruthy();
  });

  it('renders the modal title when open', async () => {
    await act(async () => {
      renderWithProviders(
        <SampleProjectModal open={true} onClose={vi.fn()} onSuccess={vi.fn()} />
      );
    });
    expect(screen.getByText('Setting up your sample project')).toBeDefined();
  });

  it('shows setup description text', async () => {
    await act(async () => {
      renderWithProviders(
        <SampleProjectModal open={true} onClose={vi.fn()} onSuccess={vi.fn()} />
      );
    });
    expect(screen.getByText(/creating a sample project/i)).toBeDefined();
  });

  it('shows Creating project step label', async () => {
    await act(async () => {
      renderWithProviders(
        <SampleProjectModal open={true} onClose={vi.fn()} onSuccess={vi.fn()} />
      );
    });
    expect(screen.getByText('Creating project')).toBeDefined();
  });

  it('modal hidden when open=false', () => {
    const { container } = renderWithProviders(
      <SampleProjectModal open={false} onClose={vi.fn()} onSuccess={vi.fn()} />
    );
    const modal = container.querySelector('.cds--modal');
    expect(modal?.classList.contains('is-visible') ?? false).toBe(false);
  });
});
