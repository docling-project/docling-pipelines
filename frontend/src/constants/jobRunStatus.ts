/**
 * @fileoverview Job run status constants and status set definitions.
 * Status strings match Python's ExecutionStatus enum (Title-Case as serialised by FastAPI).
 * Also contains poll timing and retry constants used by useJobRunPoller.
 */

export const JOB_RUN_STATUS = {
  PENDING: 'Pending',
  STARTING: 'Starting',
  RUNNING: 'Running',
  COMPLETED: 'Completed',
  FAILED: 'Failed',
  // Backend serialises ExecutionStatus.CANCELED as "Canceled" (one L).
  CANCELED: 'Canceled',
  CANCELING: 'Canceling',
  WARNING: 'Warning',
  COMPLETED_WITH_ERRORS: 'CompletedWithErrors',
  COMPLETED_WITH_WARNINGS: 'CompletedWithWarnings',
  SKIPPED: 'Skipped',
} as const;

export type JobRunStatus = (typeof JOB_RUN_STATUS)[keyof typeof JOB_RUN_STATUS];

/** Run has reached a terminal state — stop polling. */
export const COMPLETED_STATUSES = new Set<string>([
  JOB_RUN_STATUS.COMPLETED,
  JOB_RUN_STATUS.FAILED,
  JOB_RUN_STATUS.CANCELED,
  JOB_RUN_STATUS.COMPLETED_WITH_ERRORS,
  JOB_RUN_STATUS.COMPLETED_WITH_WARNINGS,
]);

/** Run is actively executing — show node loading-decoration. */
export const RUNNING_STATUSES = new Set<string>([
  JOB_RUN_STATUS.STARTING,
  JOB_RUN_STATUS.RUNNING,
  JOB_RUN_STATUS.CANCELING,
]);

/** Stop button is disabled in these states. */
export const STOP_DISABLED_STATUSES = new Set<string>([
  JOB_RUN_STATUS.PENDING,
  JOB_RUN_STATUS.STARTING,
  JOB_RUN_STATUS.CANCELING,
]);

// ── Poll timing ───────────────────────────────────────────────────────────────

/** Regular poll interval — how often to fetch job run status while running (ms). */
export const POLL_INTERVAL_MS = 10_000;

/** Delay before the one-shot final poll after a terminal status (ms). */
export const POLL_FINAL_DELAY_MS = 5_000;

/** Maximum number of consecutive 404 retries before the poll gives up. */
export const POLL_MAX_RETRIES = 6;
