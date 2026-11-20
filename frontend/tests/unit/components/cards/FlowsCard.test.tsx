import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, act, waitFor, fireEvent } from '@testing-library/react';
import { FlowsCard } from '@/components/cards';
import { renderWithProviders } from '../../../utils/renderWithProviders';
import { server } from '../../../mocks/server';
import { http, HttpResponse } from 'msw';
import { IntlProvider } from 'react-intl';

const mockNavigate = vi.fn();
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<any>('react-router-dom');
  return {
    ...actual,
    useNavigate: () => mockNavigate,
  };
});

function renderFlowsCard() {
  return renderWithProviders(
    <IntlProvider locale="en" messages={{}}>
      <FlowsCard />
    </IntlProvider>
  );
}

describe('FlowsCard', () => {
  beforeEach(() => {
    mockNavigate.mockClear();
  });
  it('renders without crashing', async () => {
    server.use(
      http.get('/api/flows', () => HttpResponse.json({ flows: [], total: 0 }))
    );
    await act(async () => { renderFlowsCard(); });
    // Card renders (HomeCard wraps content)
    expect(document.body).not.toBeNull();
  });

  it('renders flows from the API', async () => {
    server.use(
      http.get('/api/flows', () =>
        HttpResponse.json({
          flows: [
            {
              flow_id: 'f-1',
              name: 'My Flow',
              modified_on: new Date().toISOString(),
              project_id: 'p-1',
              run_status: 'completed',
            },
          ],
          total: 1,
        })
      )
    );
    await act(async () => { renderFlowsCard(); });
    // Wait for data to load
    await waitFor(() => expect(screen.getByText('My Flow')).toBeInTheDocument(), { timeout: 3000 });
  });

  it('shows a Flows heading', async () => {
    server.use(
      http.get('/api/flows', () => HttpResponse.json({ flows: [], total: 0 }))
    );
    await act(async () => { renderFlowsCard(); });
    expect(screen.getAllByText(/Flows/i).length).toBeGreaterThan(0);
  });

  it('displays error message when flows api fails', async () => {
    server.use(
      http.get('/api/flows', () => HttpResponse.json({ message: 'Internal Server Error' }, { status: 500 }))
    );
    await act(async () => { renderFlowsCard(); });
    await waitFor(() => {
      expect(screen.getByText('Failed to load flows.')).toBeInTheDocument();
    });
  });

  it('sorts flows correctly with missing or empty modified_on', async () => {
    server.use(
      http.get('/api/flows', () =>
        HttpResponse.json({
          flows: [
            {
              flow_id: 'f-empty-1',
              name: 'Flow Empty 1',
              modified_on: '',
              project_id: 'p-1',
              run_status: 'completed',
            },
            {
              flow_id: 'f-newer',
              name: 'Flow Newer',
              modified_on: '2024-02-01T00:00:00.000Z',
              project_id: 'p-1',
              run_status: 'completed',
            },
            {
              flow_id: 'f-older',
              name: 'Flow Older',
              modified_on: '2024-01-01T00:00:00.000Z',
              project_id: 'p-1',
              run_status: 'completed',
            },
            {
              flow_id: 'f-empty-2',
              name: 'Flow Empty 2',
              modified_on: undefined as any,
              project_id: 'p-1',
              run_status: 'completed',
            },
          ],
          total: 4,
         })
      )
    );
    await act(async () => { renderFlowsCard(); });
    await waitFor(() => expect(screen.getByText('Flow Newer')).toBeInTheDocument());

    const flowButtons = Array.from(document.querySelectorAll('button'));
    const flowNames = flowButtons
      .map((b) => b.querySelector('[class*="itemName"]')?.textContent)
      .filter(Boolean);
    expect(flowNames).toEqual(['Flow Newer', 'Flow Older', 'Flow Empty 1', 'Flow Empty 2']);
  });

  it('navigates to flow details when flow is clicked and project_id exists', async () => {
    server.use(
      http.get('/api/flows', () =>
        HttpResponse.json({
          flows: [
            {
              flow_id: 'f-1',
              name: 'My Flow with Project',
              modified_on: '2024-02-01T00:00:00.000Z',
              container_id: 'p-1',
              run_status: 'completed',
            },
          ],
          total: 1,
        })
      )
    );
    await act(async () => { renderFlowsCard(); });
    await waitFor(() => expect(screen.getByText('My Flow with Project')).toBeInTheDocument());

    const flowButton = screen.getByRole('button', { name: /My Flow with Project/i });
    fireEvent.click(flowButton);

    expect(mockNavigate).toHaveBeenCalledWith('/flows/f-1?project_id=p-1', undefined);
  });

  it('navigates to projects page when flow is clicked and project_id does not exist', async () => {
    server.use(
      http.get('/api/flows', () =>
        HttpResponse.json({
          flows: [
            {
              flow_id: 'f-no-project',
              name: 'My Flow without Project',
              modified_on: '2024-02-01T00:00:00.000Z',
              container_id: '',
              run_status: 'completed',
            },
          ],
          total: 1,
        })
      )
    );
    await act(async () => { renderFlowsCard(); });
    await waitFor(() => expect(screen.getByText('My Flow without Project')).toBeInTheDocument());

    const flowButton = screen.getByRole('button', { name: /My Flow without Project/i });
    fireEvent.click(flowButton);

    expect(mockNavigate).toHaveBeenCalledWith('/projects', undefined);
  });

  it('refreshes the card content when header action is clicked', async () => {
    let apiCallCount = 0;
    server.use(
      http.get('/api/flows', () => {
        apiCallCount++;
        return HttpResponse.json({
          flows: [
            {
              flow_id: `f-${apiCallCount}`,
              name: `Flow run ${apiCallCount}`,
              modified_on: '2024-02-01T00:00:00.000Z',
              project_id: 'p-1',
              run_status: 'completed',
            },
          ],
          total: 1,
        });
      })
    );
    await act(async () => { renderFlowsCard(); });
    await waitFor(() => expect(screen.getByText('Flow run 1')).toBeInTheDocument());

    const refreshButton = screen.getByRole('button', { name: /Refresh flows/i });
    fireEvent.click(refreshButton);

    await waitFor(() => expect(screen.getByText('Flow run 2')).toBeInTheDocument());
    expect(apiCallCount).toBe(2);
  });
});
