import { describe, it, expect, vi } from 'vitest';
import { screen, fireEvent } from '@testing-library/react';
import { renderWithProviders } from '../../../utils/renderWithProviders';
import { ProjectsTable } from '@/components/Projects/ProjectsTable/ProjectsTable';
import type { ProjectRow } from '@/types';
import { PERMISSION_SCENARIOS, authPreloadedState } from '../../../mocks/fixtures/permission.fixture';

/** Overflow menu items mount asynchronously and are visibility-hidden until positioned. */
async function menuItem(name: string): Promise<HTMLElement> {
  const label = await screen.findByText(name, { selector: '.cds--overflow-menu-options__option-content' });
  return label.closest('button') as HTMLElement;
}

function row(createdBy: string | null): ProjectRow {
  return {
    id: 'proj-1',
    name: 'Alpha Project',
    description: '',
    tags: [],
    flows: 1,
    createdOn: '1/1/2024',
    lastModified: '6/1/2024',
    createdOnRaw: '2024-01-01T00:00:00Z',
    lastModifiedRaw: '2024-06-01T00:00:00Z',
    createdBy,
  };
}

function renderTable(role: (typeof PERMISSION_SCENARIOS)[number]['role'], createdBy: string | null) {
  const handlers = {
    onNewProject: vi.fn(),
    onOpenProject: vi.fn(),
    onRefresh: vi.fn(),
    onDeleteProject: vi.fn(() => Promise.resolve()),
    onEditProject: vi.fn(() => Promise.resolve()),
  };
  renderWithProviders(<ProjectsTable rows={[row(createdBy)]} {...handlers} />, {
    preloadedState: authPreloadedState(role),
  });
  fireEvent.click(document.querySelector('.cds--overflow-menu') as HTMLElement);
  return handlers;
}

describe('ProjectsTable permission gating', () => {
  describe.each(PERMISSION_SCENARIOS)('$name', ({ role, owner, allowed, canCreate }) => {
    it('gates the new project button by role', () => {
      renderTable(role, owner);
      const button = screen.getByRole('button', { name: 'New project' });
      expect(button.hasAttribute('disabled')).toBe(!canCreate);
    });

    it('gates edit and delete by role and ownership', async () => {
      renderTable(role, owner);
      const edit = await menuItem('Edit project');
      const del = await menuItem('Delete');
      expect(edit.hasAttribute('disabled')).toBe(!allowed);
      expect(del.hasAttribute('disabled')).toBe(!allowed);
      // View stays available for everyone
      expect((await menuItem('View project')).hasAttribute('disabled')).toBe(false);
    });
  });

  it('explains a missing role on the new project button and the disabled items', async () => {
    renderTable('viewer', 'me');
    expect(screen.getByText('You need the editor role to do this', { selector: '[role="tooltip"] *' })).toBeInTheDocument();
    expect(await menuItem('Delete')).toHaveAttribute('title', 'You need the editor role to do this');
  });

  it('explains foreign ownership with a title on the disabled items', async () => {
    renderTable('editor', 'someone-else');
    expect(await menuItem('Edit project'))
      .toHaveAttribute('title', 'Only the owner or an administrator can change this');
  });

  it('keeps project navigation available for a viewer', () => {
    const { onOpenProject } = renderTable('viewer', 'me');
    fireEvent.click(screen.getByText('Alpha Project'));
    expect(onOpenProject).toHaveBeenCalledWith('proj-1');
  });
});
