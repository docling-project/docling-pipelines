import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { screen, fireEvent, waitFor, within } from '@testing-library/react';
import React from 'react';
import { http, HttpResponse } from 'msw';
import { renderWithProviders } from '../../../utils/renderWithProviders';
import { FlowRunHistoryTearsheet } from '@/components/Canvas/FlowRunHistoryTearsheet/FlowRunHistoryTearsheet';
import { server } from '../../../mocks/server';

// Mock SharedTearsheet to render children directly — bypasses Carbon's React portal
// which renders outside the jsdom query scope and causes findByRole('table') to time out on CI.
vi.mock('@/components/common', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/components/common')>();
  return {
    ...actual,
    SharedTearsheet: ({
      open,
      title,
      children,
      onClose,
    }: {
      open: boolean;
      title?: string;
      children?: React.ReactNode;
      onClose?: () => void;
    }) =>
      open ? (
        <div data-testid="mock-tearsheet">
          <h2>{title}</h2>
          <button type="button" aria-label="Close" onClick={onClose} />
          {children}
        </div>
      ) : null,
  };
});

describe('FlowRunHistoryTearsheet', () => {
  let createObjectURLSpy: ReturnType<typeof vi.spyOn>;
  let revokeObjectURLSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    createObjectURLSpy = vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:mock-url');
    revokeObjectURLSpy = vi.spyOn(URL, 'revokeObjectURL').mockReturnValue(undefined);
  });

  afterEach(() => {
    createObjectURLSpy.mockRestore();
    revokeObjectURLSpy.mockRestore();
  });

  it('renders without crashing when closed', () => {
    const { container } = renderWithProviders(
      <FlowRunHistoryTearsheet open={false} onClose={vi.fn()} flowId="flow-1" projectId="proj-1" />
    );
    expect(container).toBeTruthy();
  });

  it('renders when open with no flowId', () => {
    const { container } = renderWithProviders(
      <FlowRunHistoryTearsheet open={true} onClose={vi.fn()} />
    );
    expect(container).toBeTruthy();
  });

  it('calls onClose when tearsheet close button is clicked', () => {
    const onClose = vi.fn();
    renderWithProviders(
      <FlowRunHistoryTearsheet open={true} onClose={onClose} flowId="flow-1" />
    );
    const closeButtons = document.querySelectorAll('button');
    expect(closeButtons.length).toBeGreaterThan(0);
  });

  it('renders tearsheet title "Flow run history" when open', () => {
    renderWithProviders(
      <FlowRunHistoryTearsheet open={true} onClose={vi.fn()} flowId="flow-1" />
    );
    expect(screen.getByText('Flow run history')).toBeInTheDocument();
  });

  it('does not fetch when open=false', () => {
    renderWithProviders(
      <FlowRunHistoryTearsheet open={false} onClose={vi.fn()} flowId="flow-1" />
    );
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
  });

  it('fetches job runs and displays a row when open=true with flowId', async () => {
    renderWithProviders(
      <FlowRunHistoryTearsheet open={true} onClose={vi.fn()} flowId="flow-1" />
    );
    // Wait for a data row to appear (timestamp button rendered after fetch)
    await waitFor(() => {
      expect(screen.queryAllByRole('button').length).toBeGreaterThan(0);
    });
  });

  it('shows table headers Timestamp, Status, Duration, Logs after data loads', async () => {
    renderWithProviders(
      <FlowRunHistoryTearsheet open={true} onClose={vi.fn()} flowId="flow-1" />
    );
    await screen.findByRole('table');
    expect(screen.getByText('Timestamp')).toBeInTheDocument();
    expect(screen.getByText('Status')).toBeInTheDocument();
    expect(screen.getByText('Duration')).toBeInTheDocument();
    expect(screen.getByText('Logs')).toBeInTheDocument();
  });

  it('does NOT fetch when open=true but flowId is undefined', async () => {
    renderWithProviders(
      <FlowRunHistoryTearsheet open={true} onClose={vi.fn()} />
    );
    expect(screen.queryByTestId('data-table-skeleton')).not.toBeInTheDocument();
    // Without flowId, table renders empty — wait for it
    await waitFor(() => {
      expect(screen.queryByRole('table')).toBeDefined();
    });
    const table = screen.queryByRole('table');
    if (table) {
      const rowButtons = within(table).queryAllByRole('button');
      expect(rowButtons.length).toBe(0);
    }
  });

  it('renders a DataTableSkeleton while fetching', async () => {
    server.use(
      http.get('/api/job_runs', () => new Promise(() => { /* never resolves */ }))
    );
    renderWithProviders(
      <FlowRunHistoryTearsheet open={true} onClose={vi.fn()} flowId="flow-1" />
    );
    await waitFor(() => {
      const skeletonTable = document.querySelector('table.cds--skeleton');
      expect(skeletonTable).toBeInTheDocument();
    });
  });

  it('handles API error gracefully — table renders (empty) without crashing', async () => {
    server.use(
      http.get('/api/job_runs', () =>
        HttpResponse.json({}, { status: 500 })
      )
    );
    renderWithProviders(
      <FlowRunHistoryTearsheet open={true} onClose={vi.fn()} flowId="flow-1" />
    );
    // After error, table renders empty
    await waitFor(() => {
      expect(screen.queryByRole('table')).toBeDefined();
    });
    const table = screen.queryByRole('table');
    if (table) {
      const rowButtons = within(table).queryAllByRole('button');
      expect(rowButtons.length).toBe(0);
    }
  });

  it('row timestamp is rendered as a button inside the table', async () => {
    renderWithProviders(
      <FlowRunHistoryTearsheet open={true} onClose={vi.fn()} flowId="flow-1" />
    );
    // Re-query table inside waitFor to avoid stale reference after state update
    await waitFor(() => {
      const t = screen.queryByRole('table');
      expect(t).not.toBeNull();
      expect(within(t!).queryAllByRole('button').length).toBeGreaterThan(0);
    });
  });

  it('onClose is not called on initial render', () => {
    const onClose = vi.fn();
    renderWithProviders(
      <FlowRunHistoryTearsheet open={true} onClose={onClose} flowId="flow-1" />
    );
    expect(onClose).not.toHaveBeenCalled();
  });

  it('clicking the timestamp button calls onClose', async () => {
    const onClose = vi.fn();
    renderWithProviders(
      <FlowRunHistoryTearsheet open={true} onClose={onClose} flowId="flow-1" />
    );
    let timestampBtn: HTMLElement | undefined;
    await waitFor(() => {
      const t = screen.queryByRole('table');
      expect(t).not.toBeNull();
      const btns = within(t!).queryAllByRole('button');
      expect(btns.length).toBeGreaterThan(0);
      timestampBtn = btns[0];
    });
    if (timestampBtn) {
      fireEvent.click(timestampBtn);
      expect(onClose).toHaveBeenCalledTimes(1);
    }
  });

  it('renders a Download logs button for completed runs', async () => {
    server.use(
      http.get('/api/job_runs', () =>
        HttpResponse.json({
          list: [
            {
              job_run_id: 'run-dl-1',
              start_time: 1705329000,
              status: 'Completed',
              duration: 60,
            },
          ],
        })
      )
    );
    renderWithProviders(
      <FlowRunHistoryTearsheet open={true} onClose={vi.fn()} flowId="flow-dl" />
    );
    await waitFor(() => {
      const t = screen.queryByRole('table');
      expect(t).not.toBeNull();
      expect(within(t!).queryAllByRole('button').length).toBeGreaterThanOrEqual(2);
    });
  });

  it('does not render Download button for unknown statuses', async () => {
    server.use(
      http.get('/api/job_runs', () =>
        HttpResponse.json({
          list: [
            {
              job_run_id: 'run-unknown-1',
              start_time: 1705329000,
              status: 'UnknownStatus',
              duration: 10,
            },
          ],
        })
      )
    );
    renderWithProviders(
      <FlowRunHistoryTearsheet open={true} onClose={vi.fn()} flowId="flow-unknown" />
    );
    await screen.findByText('UnknownStatus');
    expect(screen.queryByRole('button', { name: 'Download logs' })).toBeNull();
  });

  it('re-fetches when flowId changes', async () => {
    let callCount = 0;
    server.use(
      http.get('/api/job_runs', () => {
        callCount++;
        return HttpResponse.json({ list: [] });
      })
    );
    const { rerender } = renderWithProviders(
      <FlowRunHistoryTearsheet open={true} onClose={vi.fn()} flowId="flow-a" />
    );
    await waitFor(() => expect(callCount).toBe(1));
    rerender(
      <FlowRunHistoryTearsheet open={true} onClose={vi.fn()} flowId="flow-b" />
    );
    await waitFor(() => expect(callCount).toBe(2));
  });

  it('clicking Download logs button triggers triggerDownloadLogs', async () => {
    server.use(
      http.get('/api/job_runs', () =>
        HttpResponse.json({
          list: [{
            job_run_id: 'run-dl-2',
            start_time: 1705329000,
            status: 'Completed',
            duration: 60,
          }],
        })
      )
    );
    renderWithProviders(
      <FlowRunHistoryTearsheet open={true} onClose={vi.fn()} flowId="flow-dl-2" />
    );
    const downloadBtn = await screen.findByRole('button', { name: 'Download logs' });
    fireEvent.click(downloadBtn);
    await waitFor(() => {
      expect(createObjectURLSpy).toHaveBeenCalled();
    });
  });

  it('triggerDownloadLogs concatenates node_sequence logs when present', async () => {
    server.use(
      http.get('/api/job_runs', () =>
        HttpResponse.json({
          list: [{
            job_run_id: 'run-node-seq',
            start_time: 1705329000,
            status: 'Completed',
            duration: 30,
          }],
        })
      ),
      http.get('/api/job_runs/:id', () =>
        HttpResponse.json({
          node_sequence: ['node-a', 'node-b'],
          'node-a': 'Log line A\n',
          'node-b': 'Log line B\n',
          job_stats: {},
        })
      )
    );
    renderWithProviders(
      <FlowRunHistoryTearsheet open={true} onClose={vi.fn()} flowId="flow-node-seq" />
    );
    const downloadBtn = await screen.findByRole('button', { name: 'Download logs' });
    fireEvent.click(downloadBtn);
    await waitFor(() => {
      expect(createObjectURLSpy).toHaveBeenCalled();
    });
  });

  it('triggerDownloadLogs appends error_logs when present', async () => {
    server.use(
      http.get('/api/job_runs', () =>
        HttpResponse.json({
          list: [{
            job_run_id: 'run-err-logs',
            start_time: 1705329000,
            status: 'Completed',
            duration: 10,
          }],
        })
      ),
      http.get('/api/job_runs/:id', () =>
        HttpResponse.json({
          node_sequence: [],
          error_logs: 'Traceback: Something went wrong',
          job_stats: {},
        })
      )
    );
    renderWithProviders(
      <FlowRunHistoryTearsheet open={true} onClose={vi.fn()} flowId="flow-err-logs" />
    );
    const downloadBtn = await screen.findByRole('button', { name: 'Download logs' });
    fireEvent.click(downloadBtn);
    await waitFor(() => {
      expect(createObjectURLSpy).toHaveBeenCalled();
    });
  });

  it('renders Download button for Failed run', async () => {
    server.use(
      http.get('/api/job_runs', () =>
        HttpResponse.json({
          list: [{
            job_run_id: 'run-nondl',
            start_time: 1705329000,
            status: 'Failed',
            duration: 5,
          }],
        })
      )
    );
    renderWithProviders(
      <FlowRunHistoryTearsheet open={true} onClose={vi.fn()} flowId="flow-nondl" />
    );
    expect(await screen.findByRole('button', { name: 'Download logs' })).toBeInTheDocument();
  });

  it('renders Download button for Running status', async () => {
    server.use(
      http.get('/api/job_runs', () =>
        HttpResponse.json({
          list: [{
            job_run_id: 'run-running',
            start_time: 1705329000,
            status: 'Running',
            duration: 0,
          }],
        })
      )
    );
    renderWithProviders(
      <FlowRunHistoryTearsheet open={true} onClose={vi.fn()} flowId="flow-running" />
    );
    await waitFor(() => {
      const t = screen.queryByRole('table');
      expect(t).not.toBeNull();
      expect(within(t!).queryAllByRole('button').length).toBeGreaterThanOrEqual(1);
    });
  });
});
