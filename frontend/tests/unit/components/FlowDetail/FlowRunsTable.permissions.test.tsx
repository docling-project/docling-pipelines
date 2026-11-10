import { describe, it, expect, vi } from 'vitest';
import { screen, fireEvent } from '@testing-library/react';
import { renderWithProviders } from '../../../utils/renderWithProviders';
import { FlowRunsTable } from '@/components/FlowDetail/FlowRunsTable/FlowRunsTable';
import type { RunRow, RunStatus } from '@/components/FlowDetail/FlowRunsTable/FlowRunsTable';
import { PERMISSION_SCENARIOS, authPreloadedState } from '../../../mocks/fixtures/permission.fixture';

function run(status: RunStatus, userId: string | null): RunRow {
  return {
    run_id: 'run-1',
    start_time: '8/1/2024, 9:00 AM',
    start_time_epoch: 1722500000,
    status,
    duration: '00:01:30',
    duration_seconds: 90,
    user_id: userId,
  };
}

/** Overflow menu items mount asynchronously and are visibility-hidden until positioned. */
async function menuItem(name: string): Promise<HTMLElement> {
  const label = await screen.findByText(name, { selector: '.cds--overflow-menu-options__option-content' });
  return label.closest('button') as HTMLElement;
}

function renderTable(role: (typeof PERMISSION_SCENARIOS)[number]['role'], status: RunStatus, userId: string | null) {
  const handlers = { onRefresh: vi.fn(), onDeleteRun: vi.fn(), onCancelRun: vi.fn(), onViewRun: vi.fn() };
  renderWithProviders(<FlowRunsTable runs={[run(status, userId)]} isLoading={false} {...handlers} />, {
    preloadedState: authPreloadedState(role),
  });
  fireEvent.click(document.querySelector('.cds--overflow-menu') as HTMLElement);
  return handlers;
}

describe('FlowRunsTable permission gating', () => {
  describe.each(PERMISSION_SCENARIOS)('$name', ({ role, owner, allowed }) => {
    it('gates delete run by role and run ownership', async () => {
      renderTable(role, 'run', owner);
      expect((await menuItem('Delete')).hasAttribute('disabled')).toBe(!allowed);
      expect((await menuItem('View run')).hasAttribute('disabled')).toBe(false);
    });

    it('gates cancel run by role and run ownership', async () => {
      renderTable(role, 'in_progress', owner);
      expect((await menuItem('Cancel run')).hasAttribute('disabled')).toBe(!allowed);
      expect((await menuItem('View run')).hasAttribute('disabled')).toBe(false);
    });
  });

  it('explains a missing role on the disabled items', async () => {
    renderTable('viewer', 'run', 'me');
    expect(await menuItem('Delete')).toHaveAttribute('title', 'You need the editor role to do this');
  });

  it('explains a foreign run on the disabled items', async () => {
    renderTable('editor', 'in_progress', 'someone-else');
    expect(await menuItem('Cancel run'))
      .toHaveAttribute('title', 'Only the owner or an administrator can change this');
  });

  it('keeps run viewing available for a viewer', () => {
    const { onViewRun } = renderTable('viewer', 'run', 'me');
    fireEvent.click(screen.getByText('8/1/2024, 9:00 AM'));
    expect(onViewRun).toHaveBeenCalledWith('run-1');
  });
});
