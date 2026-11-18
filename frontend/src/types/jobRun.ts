/**
 * @fileoverview Job run-related type definitions.
 * Covers both API wire types (HTTP responses/requests) and Redux state shapes.
 */

// ── API wire types ───────────────────────────────────────────────────────

/**
 * Job run list item from the backend API response.
 */
export interface JobRunListItem {
  job_run_id: string;
  job_id: string;
  flow_name?: string | null;
  status: string;
  message: string;
  start_time: number;
  end_time: number;
  duration: number;
  total_docs: number;
  processed_docs: number;
  completed_docs: number;
  failed_docs: number;
  skipped_docs: number;
  orchestrator: string;
  user_id: string | null;
}

/**
 * Response envelope for job run list operations.
 */
export interface JobRunListResponse {
  list: JobRunListItem[];
  count: number;
  total: number;
}

/**
 * Response for job run creation.
 */
export interface JobRunCreateResponse {
  job_run_id: string;
  status: string;
  message: string;
}

/**
 * Node statistics from job run execution.
 * Maps to the `NodeStatsDto` shape returned by the Python backend.
 */
export interface NodeStats {
  id: string;
  name: string;
  node_status: string;
  error: string;
  start_time: number;
  end_time: number;
  time_taken: number;
  col_names: string[];
  total_docs: number;
  failed_docs: number;
  skipped_docs: number;
  docs_completed: number;
  docs_completed_count: number;
  node_metadata: Record<string, unknown> | null;
  batch_id: string | null;
  batch_num: number | null;
}

/**
 * Node metadata item from job run.
 * Maps to the `NodeMetadataItem` shape returned by the Python backend.
 */
export interface NodeMetadataItem {
  id: string;
  operator: string;
  node_metadata: Record<string, unknown> | null;
}

/**
 * Overall job statistics from execution.
 * Maps to the `JobStatsDto` shape returned by the Python backend.
 */
export interface JobStats {
  job_id: string;
  job_run_id: string;
  status: string;
  message: string;
  start_time: number;
  end_time: number;
  duration: number;
  heartbeat_timestamp: number | null;
  progress_timestamp: number;
  total_docs: number;
  processed_docs: number;
  completed_docs: number | null;
  failed_docs: number;
  skipped_docs: number;
  deleted_doc_count: number;
  total_pages_processed: number;
  page_type_stats: Record<string, number> | null;
  execution_time: number | null;
  orchestrator: string;
  container_kind: string | null;
  container_id: string | null;
  flow_id: string | null;
  user_id: string | null;
  account_id: string | null;
  user_entitlements: Record<string, unknown> | null;
  report_status: string | null;
  report_generation_started_at: number | null;
  report_generation_completed_at: number | null;
  node_stats: Record<string, NodeStats>;
  batch_node_stats: Record<string, Record<string, NodeStats>>;
}

/**
 * Response for job run status.
 */
export interface JobRunStatusResponse {
  node_sequence: string[];
  job_stats: JobStats;
  node_metadata: NodeMetadataItem[];
  /**
   * Frozen copy of the flow definition as it existed when this run was triggered.
   * Use this to render the historical flow graph — never use the live flow definition
   * from GET /flows/{flow_id}, which may have changed since the run executed.
   * Null for older runs or CLI-only runs where no snapshot was captured.
   */
  flow_snapshot: Record<string, unknown> | null;
  [key: string]: unknown;
}

/**
 * Request body for creating a job run.
 * Maps to the `JobsAPIExecuteModel` shape consumed by the Python backend.
 */
export interface JobRunCreateRequest {
  entity: {
    job: {
      asset_ref: string;
      asset_ref_type: string;
      name?: string;
      description?: string;
      configuration?: Record<string, string>;
      job_parameters?: Array<{ name: string; value: string }>;
    };
    job_run?: {
      configuration?: {
        user_id?: string;
        metadata?: Record<string, string>;
        [key: string]: unknown;
      };
      job_parameters?: Array<{ name: string; value: string }>;
    };
  };
}

/**
 * Response for job run cancellation.
 */
export interface JobRunCancelResponse {
  job_run_id: string;
  status: string;
  message: string;
}

// ── Redux state types ────────────────────────────────────────────────────

/**
 * @fileoverview Job run-related type definitions for Redux state management.
 * Defines the structure of job runs, execution logs, statistics, and the job run state slice.
 */

/**
 * Represents a single log entry from a job run execution.
 * Contains timestamped messages from pipeline execution.
 */
export interface LogEntry {
  /** ISO 8601 timestamp when the log entry was created */
  timestamp?: string;
  /** Log level (e.g., "info", "warning", "error") */
  level?: string;
  /** Log message content */
  message?: string;
  /** ID of the node/operator that generated this log */
  nodeId?: string;
  /** Additional dynamic properties */
  [key: string]: unknown;
}

/**
 * Represents execution statistics for a job run.
 * Contains timing, status, and performance metrics.
 */
export interface RunStats {
  /** Total execution duration in milliseconds */
  duration?: number;
  /** Current or final status of the run */
  status?: string;
  /** ISO 8601 timestamp when execution started */
  startTime?: string;
  /** ISO 8601 timestamp when execution ended */
  endTime?: string;
  /** Performance and execution metrics */
  metrics?: Record<string, any>;
  /** Per-node execution statistics */
  nodeStats?: Record<string, any>;
  /** Additional dynamic properties */
  [key: string]: unknown;
}

/**
 * Represents a single job run execution instance.
 * Contains basic information about a pipeline execution.
 */
export interface JobRun {
  /** Unique identifier for this job run */
  jobRunId?: string;
  /** ID of the parent job */
  jobId?: string;
  /** Name of the executed flow */
  flowName?: string | null;
  /** Current execution status */
  status?: string;
  /** ISO 8601 timestamp when execution started */
  startTime?: string;
  /** ISO 8601 timestamp when execution ended */
  endTime?: string;
  /** Additional dynamic properties */
  [key: string]: unknown;
}

/**
 * Redux state slice for managing job run executions, logs, and statistics.
 * Stores multiple job runs with their associated execution data.
 */
export interface JobRunState {
  /** Map of job run IDs to their data */
  items: Record<string, JobRun>;
  /** Index mapping job IDs to arrays of their run IDs */
  byJobId: Record<string, string[]>;
  /** Currently selected job run ID for detail view */
  selectedRunId: string | null;
  /** Map of job run IDs to their log entries */
  logs: Record<string, LogEntry[]>;
  /** Map of job run IDs to their execution statistics */
  statistics: Record<string, RunStats>;
  /** Loading state for async operations */
  loading: boolean;
  /** Error message if an operation failed, null otherwise */
  error: string | null;
  /** true while execution is in-flight */
  isRunning: boolean;
  /** job_run_id being viewed on canvas, or null */
  currentJobRunId: string | null;
  /** job_id (= flow_id) being viewed on canvas, or null */
  currentJobId: string | null;
  /** Latest polled JobRunStatusResponse; null when not in run-viewer mode */
  executionLogs: JobRunStatusResponse | null;
}
