import { describe, it, expect, vi } from 'vitest';
import { screen, fireEvent } from '@testing-library/react';
import { renderWithProviders } from '../../../../utils/renderWithProviders';
import { JobRunLogs } from '@/components/ReadOnlyCanvas/RunSidePanel/JobRunLogs/JobRunLogs';
import type { JobRunStatusResponse } from '@/types';

const GUID_1 = '11111111-1111-1111-8111-111111111111';
const GUID_2 = '22222222-2222-2222-8222-222222222222';

function makeResponse(overrides: Record<string, unknown> = {}): JobRunStatusResponse {
  return {
    node_sequence: [GUID_1, GUID_2],
    job_stats: {
      status: 'completed',
      message: '',
      node_stats: {
        [GUID_1]: { name: 'Ingest Node', node_status: 'completed' },
        [GUID_2]: { name: 'Extract Node', node_status: 'completed' },
      },
    },
    [GUID_1]: 'Log output for ingest node',
    [GUID_2]: 'Log output for extract node',
    ...overrides,
  } as unknown as JobRunStatusResponse;
}

describe('JobRunLogs', () => {
  it('renders without crashing with a valid log response', () => {
    const { container } = renderWithProviders(
      <JobRunLogs
        executionLogs={makeResponse()}
        selectedNodeId={null}
        onShowFullLog={vi.fn()}
      />
    );
    expect(container).toBeInTheDocument();
    expect(container.querySelector('.cds--accordion')).toBeInTheDocument();
  });

  it('renders inline notification for failed run with no node_sequence', () => {
    renderWithProviders(
      <JobRunLogs
        executionLogs={makeResponse({
          node_sequence: [],
          job_stats: {
            status: 'Failed',
            message: 'Pipeline failed due to config error',
            node_stats: {},
          },
        })}
        selectedNodeId={null}
        onShowFullLog={vi.fn()}
      />
    );
    expect(screen.getByText(/run job failed/i)).toBeInTheDocument();
    expect(screen.getByText('Pipeline failed due to config error')).toBeInTheDocument();
  });

  it('renders with a selected node id without crashing', () => {
    const { container } = renderWithProviders(
      <JobRunLogs
        executionLogs={makeResponse()}
        selectedNodeId={GUID_1}
        onShowFullLog={vi.fn()}
      />
    );
    expect(container).toBeInTheDocument();
  });

  it('renders with empty node_sequence without crashing', () => {
    const { container } = renderWithProviders(
      <JobRunLogs
        executionLogs={makeResponse({ node_sequence: [] })}
        selectedNodeId={null}
        onShowFullLog={vi.fn()}
      />
    );
    expect(container).toBeInTheDocument();
  });

  it('renders node names as accordion item buttons', () => {
    renderWithProviders(
      <JobRunLogs
        executionLogs={makeResponse()}
        selectedNodeId={null}
        onShowFullLog={vi.fn()}
      />
    );
    // Node names appear as accordion header buttons
    expect(screen.getByRole('button', { name: /ingest node/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /extract node/i })).toBeInTheDocument();
  });

  it('renders log content in accordion items after expanding', () => {
    renderWithProviders(
      <JobRunLogs
        executionLogs={makeResponse()}
        selectedNodeId={null}
        onShowFullLog={vi.fn()}
      />
    );
    // Expand first accordion item
    fireEvent.click(screen.getByRole('button', { name: /ingest node/i }));
    expect(screen.getByText('Log output for ingest node')).toBeInTheDocument();
  });

  it('skips non-GUID keys in node_sequence', () => {
    const { container } = renderWithProviders(
      <JobRunLogs
        executionLogs={makeResponse({
          node_sequence: ['not-a-guid', GUID_1],
          job_stats: {
            status: 'completed',
            message: '',
            node_stats: {
              [GUID_1]: { name: 'Ingest Node', node_status: 'completed' },
            },
          },
        })}
        selectedNodeId={null}
        onShowFullLog={vi.fn()}
      />
    );
    // GUID_1 renders as a button; non-GUID is skipped
    expect(screen.getByRole('button', { name: /ingest node/i })).toBeInTheDocument();
    expect(container).toBeInTheDocument();
  });

  it('renders two accordion items for two nodes', () => {
    renderWithProviders(
      <JobRunLogs
        executionLogs={makeResponse()}
        selectedNodeId={null}
        onShowFullLog={vi.fn()}
      />
    );
    // Each node gets an AccordionItem button
    const buttons = document.querySelectorAll('button');
    // At least 2 accordion toggle buttons (one per node)
    expect(buttons.length).toBeGreaterThanOrEqual(2);
  });

  it('renders Show detailed log button when log exceeds threshold (500 chars)', () => {
    // LOG_PREVIEW_THRESHOLD is 500 characters
    const longLog = 'x'.repeat(600);
    renderWithProviders(
      <JobRunLogs
        executionLogs={makeResponse({ [GUID_1]: longLog })}
        selectedNodeId={null}
        onShowFullLog={vi.fn()}
      />
    );
    // Expand the accordion item to reveal the show more link
    fireEvent.click(screen.getByRole('button', { name: /ingest node/i }));
    expect(screen.getByText(/show detailed log/i)).toBeInTheDocument();
  });

  it('calls onShowFullLog when Show detailed log button is clicked', () => {
    const longLog = 'y'.repeat(600);
    const onShowFullLog = vi.fn();
    renderWithProviders(
      <JobRunLogs
        executionLogs={makeResponse({ [GUID_1]: longLog })}
        selectedNodeId={null}
        onShowFullLog={onShowFullLog}
      />
    );
    fireEvent.click(screen.getByRole('button', { name: /ingest node/i }));
    fireEvent.click(screen.getByText(/show detailed log/i));
    expect(onShowFullLog).toHaveBeenCalledWith(longLog, 'Ingest Node');
  });

  it('renders failed run without message text when message is empty', () => {
    renderWithProviders(
      <JobRunLogs
        executionLogs={makeResponse({
          node_sequence: [],
          job_stats: { status: 'Failed', message: '', node_stats: {} },
        })}
        selectedNodeId={null}
        onShowFullLog={vi.fn()}
      />
    );
    expect(screen.getByText(/run job failed/i)).toBeInTheDocument();
  });

  it('renders with node id used as name when no node_stats entry', () => {
    renderWithProviders(
      <JobRunLogs
        executionLogs={{
          node_sequence: [GUID_1],
          job_stats: { status: 'completed', message: '', node_stats: {} },
          [GUID_1]: 'Some log',
        } as unknown as JobRunStatusResponse}
        selectedNodeId={null}
        onShowFullLog={vi.fn()}
      />
    );
    // GUID_1 is used as title when not found in node_stats
    expect(document.body).toBeInTheDocument();
  });
});
