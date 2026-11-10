import { describe, it, expect } from 'vitest';
import { screen, fireEvent, waitFor } from '@testing-library/react';
import { useState, type ReactNode } from 'react';
import { Routes, Route } from 'react-router-dom';
import { http, HttpResponse } from 'msw';
import { renderWithProviders } from '../../../utils/renderWithProviders';
import { FlowDetail } from '@/pages/FlowDetail/FlowDetail';
import { BreadcrumbActionsContext } from '@/contexts/BreadcrumbActionsContext';
import { server } from '../../../mocks/server';
import { flowRowFixture } from '../../../mocks/fixtures/flow.fixture';
import { PERMISSION_SCENARIOS, authPreloadedState, ME } from '../../../mocks/fixtures/permission.fixture';
import type { RootState } from '@/store';

function BreadcrumbWrapper({ children }: { children: ReactNode }) {
  const [actions, setActions] = useState<ReactNode>(null);
  return (
    <BreadcrumbActionsContext.Provider value={{ actions, setActions }}>
      {children}
      <div data-testid="breadcrumb-actions">{actions}</div>
    </BreadcrumbActionsContext.Provider>
  );
}

function runResponse(status: string, userId: string | null) {
  return {
    list: [{
      job_run_id: 'run-1', job_id: 'flow-1', status, message: '', start_time: 1705329000,
      end_time: 1705329300, duration: 300, user_id: userId,
    }],
    count: 1,
    total: 1,
  };
}

function renderPage(role: (typeof PERMISSION_SCENARIOS)[number]['role'], flowOwner: string | null = ME) {
  const base = authPreloadedState(role);
  const preloadedState: Partial<RootState> = {
    ...base,
    flow: {
      items: { 'flow-1': { ...flowRowFixture, created_by: flowOwner } },
      currentFlow: null,
      flowRunProperties: {
        enableIncrementalProcessing: false,
        retainRecordsForDeletedDocuments: false,
        validateFlow: true,
        enableNodeOutputPreview: false,
        intermediateDataStorage: 'container',
      },
      loading: false,
      error: null,
    },
  };
  return renderWithProviders(
    <BreadcrumbWrapper>
      <Routes><Route path="/flows/:flow_id" element={<FlowDetail />} /></Routes>
    </BreadcrumbWrapper>,
    { initialEntries: ['/flows/flow-1?project_id=project-1'], preloadedState }
  );
}

async function openRunMenu(): Promise<void> {
  await waitFor(() => expect(document.querySelector('.cds--overflow-menu')).not.toBeNull());
  fireEvent.click(document.querySelector('.cds--overflow-menu') as HTMLElement);
}

async function menuButton(name: string): Promise<HTMLElement> {
  const label = await screen.findByText(name, { selector: '.cds--overflow-menu-options__option-content' });
  return label.closest('button') as HTMLElement;
}

describe('FlowDetail permission gating (user_id flows from the API into the runs table)', () => {
  describe.each(PERMISSION_SCENARIOS)('$name', ({ role, owner, allowed }) => {
    it('gates delete run, keeps viewing available', async () => {
      server.use(http.get('/api/job_runs', () => HttpResponse.json(runResponse('Completed', owner))));
      renderPage(role);
      await openRunMenu();
      expect((await menuButton('Delete')).hasAttribute('disabled')).toBe(!allowed);
      expect((await menuButton('View run')).hasAttribute('disabled')).toBe(false);
    });

    it('gates cancel run', async () => {
      server.use(http.get('/api/job_runs', () => HttpResponse.json(runResponse('Running', owner))));
      renderPage(role);
      await openRunMenu();
      expect((await menuButton('Cancel run')).hasAttribute('disabled')).toBe(!allowed);
    });
  });

  it('keeps the run list and metrics available for a viewer', async () => {
    server.use(http.get('/api/job_runs', () => HttpResponse.json(runResponse('Completed', ME))));
    renderPage('viewer');
    await openRunMenu();
    expect(screen.getByText('Test Flow runs')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /view flow/i })).not.toBeDisabled();
  });

  describe.each(PERMISSION_SCENARIOS)('edit flow details: $name', ({ role, owner, allowed }) => {
    it('gates the edit button in the info panel on the flow owner', async () => {
      server.use(http.get('/api/job_runs', () => HttpResponse.json(runResponse('Completed', ME))));
      renderPage(role, owner);
      fireEvent.click(await screen.findByRole('button', { name: /about flow/i }));
      const edit = await screen.findByRole('button', { name: 'Edit flow details' });
      expect(edit.hasAttribute('disabled')).toBe(!allowed);
    });
  });
});
