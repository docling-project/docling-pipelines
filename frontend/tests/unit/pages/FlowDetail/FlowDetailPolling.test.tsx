import { describe, it, expect, vi } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import { Routes, Route } from 'react-router-dom';
import { http, HttpResponse } from 'msw';
import { renderWithProviders } from '../../../utils/renderWithProviders';
import { FlowDetail } from '@/pages/FlowDetail/FlowDetail';
import { server } from '../../../mocks/server';
import type { FlowRow } from '@/types';

// Shrink the poll interval so the polling behaviour can be observed in real time.
vi.mock('@/constants/jobRunStatus', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/constants/jobRunStatus')>();
  return { ...actual, POLL_INTERVAL_MS: 50 };
});

// Surface the first row's status/duration so the test can assert on polled data.
vi.mock('@/components/FlowDetail', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/components/FlowDetail')>();
  return {
    ...actual,
    FlowRunsTable: (props: { runs: { status: string; duration: string }[] }) => (
      <div data-testid="flow-runs-table-mock">
        {props.runs.map((r) => `${r.status}|${r.duration}`).join(',')}
      </div>
    ),
  };
});

const FLOW_STATE = {
  flow: {
    items: {
      'flow-1': {
        flow_id: 'flow-1',
        name: 'Test Flow',
        description: '',
        tags: [],
        run_count: null,
        run_status: null,
        created_on: '2024-01-01T00:00:00Z',
        modified_on: '2024-06-01T00:00:00Z',
        project_id: 'proj-1',
      } as FlowRow,
    },
    loading: false,
    error: null,
    currentFlow: null,
    flowRunProperties: {
      enableIncrementalProcessing: false,
      retainRecordsForDeletedDocuments: false,
      validateFlow: true,
      intermediateDataStorage: 'memory',
    },
  },
};

function renderFlowDetail() {
  return renderWithProviders(
    <Routes>
      <Route path="/flows/:flow_id" element={<FlowDetail />} />
    </Routes>,
    { initialEntries: ['/flows/flow-1?project_id=proj-1'], preloadedState: FLOW_STATE } as any
  );
}

const runItem = (status: string, duration: number) => ({
  job_run_id: 'run-1',
  status,
  start_time: 1705329000,
  end_time: 0,
  duration,
});

describe('FlowDetail run polling', () => {
  it('polls while a run is in progress and shows the updated duration', async () => {
    let calls = 0;
    server.use(
      http.get('/api/job_runs', () => {
        calls += 1;
        return HttpResponse.json({
          list: [runItem('Running', calls === 1 ? 0 : 5)],
          count: 1,
          total: 1,
        });
      })
    );
    renderFlowDetail();

    await waitFor(() =>
      expect(screen.getByTestId('flow-runs-table-mock').textContent).toBe('in_progress|00:00:05')
    );
    expect(calls).toBeGreaterThan(1);
  });

  it('stops polling once the run is no longer in progress', async () => {
    let calls = 0;
    server.use(
      http.get('/api/job_runs', () => {
        calls += 1;
        return HttpResponse.json({
          list: [calls === 1 ? runItem('Running', 0) : runItem('Completed', 7)],
          count: 1,
          total: 1,
        });
      })
    );
    renderFlowDetail();

    await waitFor(() =>
      expect(screen.getByTestId('flow-runs-table-mock').textContent).toBe('run|00:00:07')
    );
    const callsAtCompletion = calls;
    await new Promise((resolve) => setTimeout(resolve, 300));
    expect(calls).toBe(callsAtCompletion);
  });

  it('does not poll when no run is in progress', async () => {
    let calls = 0;
    server.use(
      http.get('/api/job_runs', () => {
        calls += 1;
        return HttpResponse.json({ list: [runItem('Completed', 7)], count: 1, total: 1 });
      })
    );
    renderFlowDetail();

    await waitFor(() =>
      expect(screen.getByTestId('flow-runs-table-mock').textContent).toBe('run|00:00:07')
    );
    await new Promise((resolve) => setTimeout(resolve, 300));
    expect(calls).toBe(1);
  });
});
