import { describe, it, expect, vi } from 'vitest';
import { screen, fireEvent } from '@testing-library/react';
import { renderWithProviders } from '../../../utils/renderWithProviders';
import { FlowsTable } from '@/components/ProjectDetail/FlowsTable/FlowsTable';
import type { FlowRow } from '@/types';
import { PERMISSION_SCENARIOS, authPreloadedState } from '../../../mocks/fixtures/permission.fixture';

function row(createdBy: string | null): FlowRow {
  return {
    flow_id: 'flow-1',
    project_id: 'proj-1',
    name: 'My Flow',
    description: '',
    tags: [],
    run_count: 2,
    run_status: null,
    created_on: '2024-01-01T00:00:00Z',
    modified_on: '2024-06-01T00:00:00Z',
    created_by: createdBy,
  };
}

/** Overflow menu items mount asynchronously and are visibility-hidden until positioned. */
async function menuItem(name: string): Promise<HTMLElement> {
  const label = await screen.findByText(name, { selector: '.cds--overflow-menu-options__option-content' });
  return label.closest('button') as HTMLElement;
}

function renderTable(role: (typeof PERMISSION_SCENARIOS)[number]['role'], createdBy: string | null) {
  const handlers = {
    onNewFlow: vi.fn(),
    onOpenFlow: vi.fn(),
    onOpenRuns: vi.fn(),
    onRefresh: vi.fn(),
    onEditFlow: vi.fn(() => Promise.resolve()),
    onDeleteFlow: vi.fn(() => Promise.resolve()),
  };
  renderWithProviders(<FlowsTable rows={[row(createdBy)]} {...handlers} />, {
    preloadedState: authPreloadedState(role),
  });
  fireEvent.click(document.querySelector('.cds--overflow-menu') as HTMLElement);
  return handlers;
}

describe('FlowsTable permission gating', () => {
  describe.each(PERMISSION_SCENARIOS)('$name', ({ role, owner, allowed, canCreate }) => {
    it('gates the new flow button by role', () => {
      renderTable(role, owner);
      expect(screen.getByRole('button', { name: 'New flow' }).hasAttribute('disabled')).toBe(!canCreate);
    });

    it('gates edit and delete by role and ownership', async () => {
      renderTable(role, owner);
      expect((await menuItem('Edit details')).hasAttribute('disabled')).toBe(!allowed);
      expect((await menuItem('Delete')).hasAttribute('disabled')).toBe(!allowed);
      expect((await menuItem('View flow')).hasAttribute('disabled')).toBe(false);
    });
  });

  it('explains a missing role on the new flow button and the disabled items', async () => {
    renderTable('viewer', 'me');
    expect(screen.getByText('You need the editor role to do this', { selector: '[role="tooltip"] *' })).toBeInTheDocument();
    expect(await menuItem('Delete')).toHaveAttribute('title', 'You need the editor role to do this');
  });

  it('explains foreign ownership on the disabled items', async () => {
    renderTable('editor', 'someone-else');
    expect(await menuItem('Edit details'))
      .toHaveAttribute('title', 'Only the owner or an administrator can change this');
  });

  it('keeps opening a flow available for a viewer', () => {
    const { onOpenFlow } = renderTable('viewer', 'me');
    fireEvent.click(screen.getByText('My Flow'));
    expect(onOpenFlow).toHaveBeenCalledWith('flow-1');
  });
});
