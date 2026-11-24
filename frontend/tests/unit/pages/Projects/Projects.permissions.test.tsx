import { describe, it, expect } from 'vitest';
import { screen, fireEvent } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { renderWithProviders } from '../../../utils/renderWithProviders';
import { Projects } from '@/pages/Projects/Projects';
import { server } from '../../../mocks/server';
import { PERMISSION_SCENARIOS, authPreloadedState } from '../../../mocks/fixtures/permission.fixture';

function projectsResponse(createdBy: string | null) {
  return {
    projects: [{
      project_id: 'proj-1',
      name: 'Owned Project',
      description: '',
      tags: [],
      flow_count: 1,
      created_on: '2024-01-01T00:00:00Z',
      modified_on: '2024-01-02T00:00:00Z',
      created_by: createdBy,
      modified_by: createdBy,
      href: null,
    }],
    total_count: 1, offset: 0, limit: 20, first: '', next: null, prev: null,
  };
}

describe('Projects page permission gating (createdBy flows from the API into the table)', () => {
  describe.each(PERMISSION_SCENARIOS)('$name', ({ role, owner, allowed, canCreate }) => {
    it('gates new project, edit and delete', async () => {
      server.use(http.get('/api/projects', () => HttpResponse.json(projectsResponse(owner))));
      renderWithProviders(<Projects />, { preloadedState: authPreloadedState(role) });

      const newProject = await screen.findByRole('button', { name: 'New project' });
      expect(newProject.hasAttribute('disabled')).toBe(!canCreate);

      fireEvent.click(document.querySelector('.cds--overflow-menu') as HTMLElement);
      const edit = (await screen.findByText('Edit project', { selector: '.cds--overflow-menu-options__option-content' })).closest('button');
      const del = (await screen.findByText('Delete', { selector: '.cds--overflow-menu-options__option-content' })).closest('button');
      expect(edit?.hasAttribute('disabled')).toBe(!allowed);
      expect(del?.hasAttribute('disabled')).toBe(!allowed);
    });
  });

  it('disables the empty-state create action for a viewer', async () => {
    server.use(http.get('/api/projects', () => HttpResponse.json({ ...projectsResponse(null), projects: [], total_count: 0 })));
    renderWithProviders(<Projects />, { preloadedState: authPreloadedState('viewer') });
    await screen.findAllByText('No projects created', {}, { timeout: 3000 });
    expect(screen.getByRole('button', { name: 'Create Project' })).toBeDisabled();
    expect(screen.getByText('You need the editor role to do this', { selector: '[role="tooltip"] *' })).toBeInTheDocument();
  });

  it('enables the empty-state create action for an editor', async () => {
    server.use(http.get('/api/projects', () => HttpResponse.json({ ...projectsResponse(null), projects: [], total_count: 0 })));
    renderWithProviders(<Projects />, { preloadedState: authPreloadedState('editor') });
    await screen.findAllByText('No projects created', {}, { timeout: 3000 });
    expect(screen.getByRole('button', { name: 'Create Project' })).not.toBeDisabled();
  });
});
