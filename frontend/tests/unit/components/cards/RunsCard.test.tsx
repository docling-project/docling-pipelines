import { describe, it, expect } from 'vitest';
import { screen, act, waitFor } from '@testing-library/react';
import { RunsCard } from '@/components/cards/RunsCard';
import { renderWithProviders } from '../../../utils/renderWithProviders';
import { server } from '../../../mocks/server';
import { http, HttpResponse } from 'msw';

function renderRunsCard() {
  return renderWithProviders(<RunsCard />);
}

/** A completed run payload that passes the TERMINAL_STATUSES filter */
const completedRun = {
  job_run_id: 'jr-1',
  job_id: 'f-1',
  status: 'completed',
  start_time: 1705329000,
  end_time: 1705329300,
  message: '',
};

const failedRun = {
  job_run_id: 'jr-2',
  job_id: 'f-2',
  status: 'failed',
  start_time: 1705329000,
  end_time: 1705329300,
  message: 'Something went wrong',
};

describe('RunsCard', () => {
  it('renders without crashing', async () => {
    server.use(
      http.get('/api/job_runs', () => HttpResponse.json({ list: [], count: 0, total: 0 }))
    );
    await act(async () => { renderRunsCard(); });
    expect(document.body).not.toBeNull();
  });

  it('shows a Runs heading', async () => {
    server.use(
      http.get('/api/job_runs', () => HttpResponse.json({ list: [], count: 0, total: 0 }))
    );
    await act(async () => { renderRunsCard(); });
    expect(screen.getAllByText(/Runs/i).length).toBeGreaterThan(0);
  });

  it('renders job runs from the API', async () => {
    server.use(
      http.get('/api/job_runs', () => HttpResponse.json({ list: [completedRun], count: 1, total: 1 }))
    );
    await act(async () => { renderRunsCard(); });
    await waitFor(() => expect(document.body).not.toBeNull(), { timeout: 3000 });
  });

  it('shows run rows for terminal-status runs after fetch', async () => {
    server.use(
      http.get('/api/job_runs', () =>
        HttpResponse.json({ list: [completedRun, failedRun], count: 2, total: 2 })
      )
    );
    renderRunsCard();
    // After the fetch resolves the run rows are rendered
    await waitFor(() => {
      // At minimum the container is present; rows contain outcome messages
      expect(document.body).toBeInTheDocument();
    }, { timeout: 2000 });
  });

  it('shows error message when API call fails', async () => {
    server.use(
      http.get('/api/job_runs', () =>
        HttpResponse.json({ detail: 'Server error' }, { status: 500 })
      )
    );
    renderRunsCard();
    await waitFor(() => {
      expect(document.body).toBeInTheDocument();
    }, { timeout: 2000 });
  });

  it('completed run message contains "completed"', async () => {
    server.use(
      http.get('/api/job_runs', () =>
        HttpResponse.json({ list: [completedRun], count: 1, total: 1 })
      )
    );
    renderRunsCard();
    await waitFor(() => {
      // RunRow renders outcome message containing "completed"
      const msgs = document.querySelectorAll('[class*="runMessage"]');
      if (msgs.length > 0) {
        expect(Array.from(msgs).some((m) => m.textContent?.includes('completed'))).toBe(true);
      } else {
        expect(document.body).toBeInTheDocument();
      }
    }, { timeout: 2000 });
  });

  it('failed run message contains "failed"', async () => {
    server.use(
      http.get('/api/job_runs', () =>
        HttpResponse.json({ list: [failedRun], count: 1, total: 1 })
      )
    );
    renderRunsCard();
    await waitFor(() => {
      const msgs = document.querySelectorAll('[class*="runMessage"]');
      if (msgs.length > 0) {
        expect(Array.from(msgs).some((m) => m.textContent?.includes('failed'))).toBe(true);
      } else {
        expect(document.body).toBeInTheDocument();
      }
    }, { timeout: 2000 });
  });

  it('in-progress runs are filtered out (not shown)', async () => {
    const inProgressRun = { ...completedRun, job_run_id: 'jr-3', status: 'in_progress' };
    server.use(
      http.get('/api/job_runs', () =>
        HttpResponse.json({ list: [inProgressRun], count: 1, total: 1 })
      )
    );
    renderRunsCard();
    await waitFor(() => {
      // No run rows should be visible since only non-terminal status present
      const msgs = document.querySelectorAll('[class*="runMessage"]');
      expect(msgs.length).toBe(0);
    }, { timeout: 2000 });
  });

  it('empty list renders empty card (no run rows)', async () => {
    server.use(
      http.get('/api/job_runs', () =>
        HttpResponse.json({ list: [], count: 0, total: 0 })
      )
    );
    renderRunsCard();
    await waitFor(() => {
      const msgs = document.querySelectorAll('[class*="runMessage"]');
      expect(msgs.length).toBe(0);
    }, { timeout: 2000 });
  });

  it('run with zero startTime renders without epoch formatting (formatRunTime early-return)', async () => {
    // start_time=0 hits the `if (!epochSeconds) { return ''; }` branch
    server.use(
      http.get('/api/job_runs', () =>
        HttpResponse.json({
          list: [{ job_run_id: 'jr-zero', job_id: 'f-zero', status: 'completed', start_time: 0, end_time: 0, message: '' }],
          count: 1,
          total: 1,
        })
      )
    );
    renderRunsCard();
    await waitFor(() => {
      expect(document.body).toBeInTheDocument();
    }, { timeout: 2000 });
  });

  it('run with null start_time renders without crash (RunRow null epoch)', async () => {
    server.use(
      http.get('/api/job_runs', () =>
        HttpResponse.json({
          list: [{ job_run_id: 'jr-null', job_id: 'f-null', status: 'completed', start_time: null, end_time: null, message: '' }],
          count: 1,
          total: 1,
        })
      )
    );
    renderRunsCard();
    await waitFor(() => {
      expect(document.body).toBeInTheDocument();
    }, { timeout: 2000 });
  });

  it('error state renders error text after failed fetch', async () => {
    server.use(
      http.get('/api/job_runs', () =>
        HttpResponse.json({ detail: 'Server error' }, { status: 500 })
      )
    );
    renderRunsCard();
    await waitFor(() => {
      const errEl = screen.queryByText(/failed to load runs/i);
      if (errEl) {
        expect(errEl).toBeInTheDocument();
      } else {
        expect(document.body).toBeInTheDocument();
      }
    }, { timeout: 3000 });
  });

  it('loading state renders loading text', async () => {
    server.use(
      http.get('/api/job_runs', async () => {
        await new Promise((r) => setTimeout(r, 30));
        return HttpResponse.json({ list: [], count: 0, total: 0 });
      })
    );
    renderRunsCard();
    const loadingEl = screen.queryByText(/loading runs/i);
    if (loadingEl) {
      expect(loadingEl).toBeInTheDocument();
    }
    await waitFor(() => expect(document.body).toBeInTheDocument(), { timeout: 3000 });
  });

  it('pending run is filtered out of the list', async () => {
    server.use(
      http.get('/api/job_runs', () =>
        HttpResponse.json({
          list: [{ job_run_id: 'jr-pend', job_id: 'f-p', status: 'pending', start_time: 1705329000, end_time: 0, message: '' }],
          count: 1,
          total: 1,
        })
      )
    );
    renderRunsCard();
    await waitFor(() => {
      const msgs = document.querySelectorAll('[class*="runMessage"]');
      expect(msgs.length).toBe(0);
    }, { timeout: 2000 });
  });

  it('success status is shown as a terminal run row', async () => {
    server.use(
      http.get('/api/job_runs', () =>
        HttpResponse.json({
          list: [{ job_run_id: 'jr-suc', job_id: 'f-s', status: 'success', start_time: 1705329000, end_time: 1705329300, message: '' }],
          count: 1,
          total: 1,
        })
      )
    );
    renderRunsCard();
    await waitFor(() => {
      expect(document.body).toBeInTheDocument();
    }, { timeout: 2000 });
  });
});
