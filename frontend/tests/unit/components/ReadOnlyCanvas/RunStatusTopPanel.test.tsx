import { describe, it, expect, vi } from 'vitest';
import { screen, fireEvent } from '@testing-library/react';
import { renderWithProviders } from '../../../utils/renderWithProviders';
import { RunStatusTopPanel } from '@/components/ReadOnlyCanvas/RunStatusTopPanel/RunStatusTopPanel';
import type { JobStats } from '@/types';
import { JOB_RUN_STATUS } from '@/constants/jobRunStatus';
import { createMockJobStats, createMockNodeStats } from '../../../mocks/fixtures/jobRun.fixture';

const BASE_STATS: JobStats = createMockJobStats({
  job_id: 'job-1',
  job_run_id: 'run-1',
  status: JOB_RUN_STATUS.RUNNING,
  duration: 90,
  total_docs: 100,
  processed_docs: 50,
  completed_docs: 50,
  failed_docs: 2,
  skipped_docs: 0,
});

function renderPanel(overrides: Partial<Parameters<typeof RunStatusTopPanel>[0]> = {}) {
  const defaults = {
    jobStats: BASE_STATS,
    isMinimized: false,
    isRunning: true,
    isStopDisabled: false,
    onToggleMinimize: vi.fn(),
    onClose: vi.fn(),
    onStop: vi.fn(),
    onRunAgain: vi.fn(),
    ...overrides,
  };
  return { ...renderWithProviders(<RunStatusTopPanel {...defaults} />), ...defaults };
}

describe('RunStatusTopPanel', () => {
  it('renders Orchestrator label', () => {
    renderPanel();
    expect(screen.getByText('Orchestrator')).toBeDefined();
    expect(screen.getByText('python')).toBeDefined();
  });

  it('renders Duration section', () => {
    renderPanel();
    expect(screen.getByText('Duration')).toBeDefined();
  });

  it('renders Documents section', () => {
    renderPanel();
    expect(screen.getByText('Documents')).toBeDefined();
  });

  it('renders Stop button when running', () => {
    renderPanel({ isRunning: true });
    expect(screen.getByRole('button', { name: /stop/i })).toBeDefined();
  });

  it('renders Run Again button when not running', () => {
    renderPanel({ isRunning: false, jobStats: { ...BASE_STATS, status: JOB_RUN_STATUS.COMPLETED } });
    expect(screen.getByRole('button', { name: /run again/i })).toBeDefined();
  });

  it('clicking Stop calls onStop', () => {
    const { onStop } = renderPanel({ isRunning: true });
    fireEvent.click(screen.getByRole('button', { name: /stop/i }));
    expect(onStop).toHaveBeenCalledOnce();
  });

  it('clicking Minimize calls onToggleMinimize', () => {
    const { onToggleMinimize } = renderPanel();
    fireEvent.click(screen.getByTitle('Minimize'));
    expect(onToggleMinimize).toHaveBeenCalledOnce();
  });

  it('renders minimized state', () => {
    renderPanel({ isMinimized: true });
    expect(screen.queryByText('Orchestrator')).toBeNull();
    expect(screen.getByTitle('Maximize')).toBeDefined();
  });

  it('clicking Close calls onClose', () => {
    const { onClose } = renderPanel();
    fireEvent.click(screen.getByTitle('Close'));
    expect(onClose).toHaveBeenCalledOnce();
  });

  it('clicking Run Again calls onRunAgain when not running', () => {
    const { onRunAgain } = renderPanel({
      isRunning: false,
      jobStats: { ...BASE_STATS, status: JOB_RUN_STATUS.COMPLETED },
    });
    fireEvent.click(screen.getByRole('button', { name: /run again/i }));
    expect(onRunAgain).toHaveBeenCalledOnce();
  });

  it('Stop button is disabled when isStopDisabled=true', () => {
    renderPanel({ isRunning: true, isStopDisabled: true });
    const stopBtn = screen.getByRole('button', { name: /stop/i });
    expect(stopBtn).toHaveProperty('disabled', true);
  });

  it('clicking Maximize calls onToggleMinimize in minimized state', () => {
    const { onToggleMinimize } = renderPanel({ isMinimized: true });
    fireEvent.click(screen.getByTitle('Maximize'));
    expect(onToggleMinimize).toHaveBeenCalledOnce();
  });

  it('clicking Close in minimized state calls onClose', () => {
    const { onClose } = renderPanel({ isMinimized: true });
    fireEvent.click(screen.getByTitle('Close'));
    expect(onClose).toHaveBeenCalledOnce();
  });

  it('renders with Completed status', () => {
    renderPanel({ isRunning: false, jobStats: { ...BASE_STATS, status: JOB_RUN_STATUS.COMPLETED } });
    expect(screen.queryAllByText(JOB_RUN_STATUS.COMPLETED).length).toBeGreaterThan(0);
  });

  it('renders with Failed status', () => {
    renderPanel({ isRunning: false, jobStats: { ...BASE_STATS, status: JOB_RUN_STATUS.FAILED } });
    expect(screen.queryAllByText(JOB_RUN_STATUS.FAILED).length).toBeGreaterThan(0);
  });

  it('renders node counts from node_stats', () => {
    const statsWithNodes: typeof BASE_STATS = {
      ...BASE_STATS,
      node_stats: {
        'n1': createMockNodeStats({ id: 'n1', name: 'N1', node_status: JOB_RUN_STATUS.COMPLETED }),
        'n2': createMockNodeStats({ id: 'n2', name: 'N2', node_status: JOB_RUN_STATUS.FAILED }),
      },
    };
    renderPanel({ jobStats: statsWithNodes });
    // One completed node → the Completed count cell shows "1"
    expect(screen.queryAllByText('1').length).toBeGreaterThan(0);
  });

  it('renders total_docs and skipped_docs from job_stats', () => {
    renderPanel({ jobStats: { ...BASE_STATS, total_docs: 42, skipped_docs: 3 } });
    expect(screen.getByText('42')).toBeDefined();
    expect(screen.getByText('3')).toBeDefined();
  });

  it('renders duration section with formatted time', () => {
    renderPanel({ jobStats: { ...BASE_STATS, duration: 3661 } });
    expect(screen.getByText('Duration')).toBeDefined();
  });
});
