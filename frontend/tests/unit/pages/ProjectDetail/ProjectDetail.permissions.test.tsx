import { describe, it, expect } from 'vitest';
import { screen, fireEvent } from '@testing-library/react';
import { Routes, Route } from 'react-router-dom';
import { http, HttpResponse } from 'msw';
import { renderWithProviders } from '../../../utils/renderWithProviders';
import { ProjectDetail } from '@/pages/ProjectDetail/ProjectDetail';
import { server } from '../../../mocks/server';
import { projectDomainFixture } from '../../../mocks/fixtures/project.fixture';
import { PERMISSION_SCENARIOS, authPreloadedState } from '../../../mocks/fixtures/permission.fixture';
import type { RootState } from '@/store';

const PROJECT_ID = 'project-1';

function flowResponse(createdBy: string | null) {
  return {
    flow_id: 'flow-1',
    container_id: PROJECT_ID,
    container_kind: 'project',
    name: 'Owned Flow',
    description: '',
    tags: [],
    created_on: '2024-01-01T00:00:00Z',
    modified_on: '2024-01-02T00:00:00Z',
    created_by: createdBy,
    job_run_summary: null,
  };
}

function renderPage(role: (typeof PERMISSION_SCENARIOS)[number]['role']) {
  const preloadedState: Partial<RootState> = {
    ...authPreloadedState(role),
    projects: { items: { [PROJECT_ID]: projectDomainFixture }, selectedProjectId: null, loading: false, error: null },
  };
  return renderWithProviders(
    <Routes><Route path="/projects/:project_id" element={<ProjectDetail />} /></Routes>,
    { initialEntries: [`/projects/${PROJECT_ID}`], preloadedState }
  );
}

describe('ProjectDetail permission gating (created_by flows from the API into the table)', () => {
  describe.each(PERMISSION_SCENARIOS)('$name', ({ role, owner, allowed, canCreate }) => {
    it('gates new flow, edit and delete', async () => {
      server.use(http.get('/api/projects/:id/flows', () => HttpResponse.json({ flows: [flowResponse(owner)], count: 1 })));
      renderPage(role);

      const newFlow = await screen.findByRole('button', { name: 'New flow' });
      expect(newFlow.hasAttribute('disabled')).toBe(!canCreate);

      await screen.findByText('Owned Flow');
      fireEvent.click(document.querySelector('.cds--overflow-menu') as HTMLElement);
      const edit = (await screen.findByText('Edit details', { selector: '.cds--overflow-menu-options__option-content' })).closest('button');
      const del = (await screen.findByText('Delete', { selector: '.cds--overflow-menu-options__option-content' })).closest('button');
      expect(edit?.hasAttribute('disabled')).toBe(!allowed);
      expect(del?.hasAttribute('disabled')).toBe(!allowed);
    });
  });

  it.each([
    { role: 'viewer', disabled: true },
    { role: 'editor', disabled: false },
    { role: 'admin', disabled: false },
  ] as const)('gates the empty-state create flow action for $role', async ({ role, disabled }) => {
    server.use(http.get('/api/projects/:id/flows', () => HttpResponse.json({ flows: [], count: 0 })));
    renderPage(role);
    await screen.findAllByText(/no flows created/i);
    const create = screen.getByRole('button', { name: /^create flow$/i });
    expect(create.hasAttribute('disabled')).toBe(disabled);
    if (disabled) {
      expect(screen.getByText('You need the editor role to do this', { selector: '[role="tooltip"] *' })).toBeInTheDocument();
    }
  });
});
