import React, { useCallback, useEffect } from 'react';
import { type CarbonIconType, Renew, CheckmarkFilled, ErrorFilled } from '@carbon/icons-react';
import { useIntl } from 'react-intl';
import { useAppDispatch, useAppSelector } from '@/hooks';
import { getJobRuns } from '@/services/api';
import { setJobRuns, setLoading, setError } from '@/slices/jobRunSlice';
import { selectJobRunsArray, selectJobRunLoading, selectJobRunError } from '@/selectors';
import { makeSelectFlowName } from '@/selectors/flowSelectors';
import type { JobRun } from '@/types';
import { HomeCard } from '../HomeCard';
import { messages } from './RunsCard.messages';
import cardStyles from '../HomeCard/HomeCard.module.scss';
import styles from './RunsCard.module.scss';

const MAX_ROWS = 5;

/** Statuses that represent a completed execution outcome (success or failure). */
const TERMINAL_STATUSES = new Set(['completed', 'success', 'failed', 'error']);

type StatusIconResult = { Icon: CarbonIconType; className: string };

/**
 * Returns a Carbon icon component and CSS class name for a given job run status.
 */
function getStatusIcon(status: string): StatusIconResult {
  switch (status?.toLowerCase()) {
    case 'completed':
    case 'success':
      return { Icon: CheckmarkFilled, className: styles.statusSuccess! };
    default:
      return { Icon: ErrorFilled, className: styles.statusError! };
  }
}

/**
 * Formats a Unix epoch (seconds) into a locale time string.
 * Returns an empty string if the value is falsy.
 */
function formatRunTime(epochSeconds: number): string {
  if (!epochSeconds) { return ''; }
  return new Date(epochSeconds * 1000).toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

/**
 * Single run row — reads the flow name from the Redux store using the run's
 * `jobId` (= flow_id) so each row can resolve its own name without an extra fetch.
 */
function RunRow({ run }: { run: JobRun }): React.JSX.Element {
  const intl = useIntl();
  const storeFlowName = useAppSelector(makeSelectFlowName(String(run.jobId ?? '')));
  const flowName = run.flowName ?? storeFlowName;
  const { Icon, className: iconClass } = getStatusIcon(String(run.status ?? ''));
  const startEpoch = run.startTime ? Math.floor(new Date(run.startTime).getTime() / 1000) : 0;
  const isSuccess = ['completed', 'success'].includes((run.status ?? '').toLowerCase());
  const label = flowName ?? String(run.jobId ?? '').slice(0, 8);
  const outcomeMessage = intl.formatMessage(
    isSuccess ? messages.runCompleted : messages.runFailed,
    { label, time: formatRunTime(startEpoch) }
  );

  return (
    <div className={styles.runRow}>
      <Icon size={16} className={`${styles.statusIcon} ${iconClass}`} />
      <div className={styles.runContent}>
        <span className={styles.runMessage}>{outcomeMessage}</span>
      </div>
    </div>
  );
}

/**
 * Home page card showing the 5 most recent completed or failed job runs.
 *
 * - Fetches runs on mount via `GET /api/job_runs?limit=5`.
 * - Only terminal statuses (completed/success/failed/error) are shown —
 *   in-progress or pending runs are excluded.
 * - Each row renders a status icon (green/red), a message, and a timestamp.
 * - The refresh icon re-fetches without navigating.
 * - Capped at 5 rows; no "View all" link (runs are project-scoped).
 */
export function RunsCard(): React.JSX.Element {
  const intl = useIntl();
  const dispatch = useAppDispatch();

  const runs = useAppSelector(selectJobRunsArray);
  const loading = useAppSelector(selectJobRunLoading);
  const error = useAppSelector(selectJobRunError);

  const fetchRuns = useCallback((): void => {
    dispatch(setLoading(true));
    getJobRuns({ limit: MAX_ROWS })
      .then((res) => {
        const map = Object.fromEntries(
          res.data.list.map((r) => [r.job_run_id, {
            jobRunId: r.job_run_id,
            jobId: r.job_id,
            flowName: r.flow_name,
            status: r.status,
            startTime: r.start_time ? new Date(r.start_time * 1000).toISOString() : '',
            message: r.message,
          }])
        );
        dispatch(setJobRuns(map));
      })
      .catch(() => {
        dispatch(setError(intl.formatMessage(messages.loadError)));
      })
      .finally(() => {
        dispatch(setLoading(false));
      });
  }, [dispatch, intl]);

  useEffect(() => {
    fetchRuns();
  }, [fetchRuns]);

  const rows = runs
    .slice()
    .filter((r) => TERMINAL_STATUSES.has((r.status ?? '').toLowerCase()))
    .sort((a, b) => (b.startTime ?? '').localeCompare(a.startTime ?? ''))
    .slice(0, MAX_ROWS);

  let cardChildren: React.ReactNode = null;

  if (loading) {
    cardChildren = <p className={cardStyles.itemLoading}>{intl.formatMessage(messages.loading)}</p>;
  } else if (error) {
    cardChildren = <p className={cardStyles.itemError}>{error}</p>;
  } else if (rows.length > 0) {
    cardChildren = (
      <ul className={cardStyles.itemList}>
        {rows.map((run) => (
          <li key={run.jobRunId}>
            <RunRow run={run} />
          </li>
        ))}
      </ul>
    );
  }

  return (
    <HomeCard
      title={intl.formatMessage(messages.title)}
      headerIcon={Renew}
      headerIconDescription={intl.formatMessage(messages.refreshDescription)}
      onHeaderAction={fetchRuns}
      emptyTitle={intl.formatMessage(messages.emptyTitle)}
      emptySubtitle={intl.formatMessage(messages.emptySubtitle)}
    >
      {cardChildren}
    </HomeCard>
  );
}
