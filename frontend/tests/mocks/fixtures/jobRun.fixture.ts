import type { JobRun, JobRunStatusResponse, JobStats } from '@/types';

/**
 * Factory function to create a mock JobStats object with default values.
 *
 * @param partial Optional partial JobStats properties to override defaults.
 * @returns Complete JobStats object.
 */
export function createMockJobStats(partial?: Partial<JobStats>): JobStats {
  return {
    job_id: 'flow-1',
    job_run_id: 'run-1',
    status: 'Completed',
    message: 'Flow completed successfully',
    start_time: 1705329000,
    end_time: 1705329300,
    duration: 300,
    heartbeat_timestamp: null,
    progress_timestamp: 1705329000,
    total_docs: 10,
    processed_docs: 10,
    completed_docs: 10,
    failed_docs: 0,
    skipped_docs: 0,
    deleted_doc_count: 0,
    total_pages_processed: 20,
    page_type_stats: null,
    execution_time: 300,
    orchestrator: 'python',
    container_kind: 'project',
    container_id: 'project-1',
    flow_id: 'flow-1',
    user_id: null,
    account_id: null,
    user_entitlements: null,
    report_status: null,
    report_generation_started_at: null,
    report_generation_completed_at: null,
    node_stats: {},
    batch_node_stats: {},
    ...partial,
  };
}

export const jobRunFixture: JobRun = {
  jobRunId: 'run-1',
  jobId: 'flow-1',
  status: 'Completed',
  startTime: '2024-01-15T10:00:00Z',
  endTime: '2024-01-15T10:05:00Z',
};

export const jobRunStatusResponseFixture: JobRunStatusResponse = {
  node_sequence: ['node-1', 'node-2'],
  job_stats: createMockJobStats(),
  node_metadata: [],
  flow_snapshot: null,
};
