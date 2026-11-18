import React from 'react';
import {
  CheckmarkFilled,
  InProgress,
  WarningFilled,
  ErrorFilled,
  Misuse,
} from '@carbon/icons-react';
import { useIntl } from 'react-intl';
import { messages } from './FlowMetrics.messages';
import styles from './FlowMetrics.module.scss';

/**
 * Pre-computed run count totals passed from {@link FlowDetail} to {@link FlowMetrics}.
 * Each field is derived by filtering `runs` by status — no API call is made here.
 */
export interface RunMetrics {
  /** Total number of job runs fetched. */
  total: number;
  /** Runs that completed successfully (`status === 'run'`). */
  run: number;
  /** Runs that are currently in-flight (`status === 'in_progress'`). */
  in_progress: number;
  /** Runs that completed but with warnings or errors (`status === 'run_with_issues'`). */
  run_with_issues: number;
  /** Runs that failed (`status === 'failed'`). */
  failed: number;
  /** Runs that were cancelled (`status === 'cancelled'`). */
  cancelled: number;
}

interface FlowMetricsProps {
  readonly metrics: RunMetrics;
}

/**
 * Five metric tiles displaying run counts by status for the current flow.
 *
 * Pure display component — receives pre-computed {@link RunMetrics} from
 * {@link FlowDetail}. Has no state, makes no API calls.
 */
export function FlowMetrics({ metrics }: FlowMetricsProps): React.JSX.Element {
  const intl = useIntl();
  return (
    <div className={styles.metricsSection}>
      <p className={styles.metricsTitle}>{intl.formatMessage(messages.metricsTitle, { total: metrics.total })}</p>
      <div className={styles.metricsTiles}>
        <div className={styles.metricTile}>
          <span className={styles.metricValue}>
            {metrics.run}<CheckmarkFilled size={16} className={styles.iconRun} />
          </span>
          <span className={styles.metricLabel}>{intl.formatMessage(messages.labelRun)}</span>
        </div>
        <div className={styles.metricTile}>
          <span className={styles.metricValue}>
            {metrics.in_progress}<InProgress size={16} className={styles.iconProgress} />
          </span>
          <span className={styles.metricLabel}>{intl.formatMessage(messages.labelInProgress)}</span>
        </div>
        <div className={styles.metricTile}>
          <span className={styles.metricValue}>
            {metrics.run_with_issues}<WarningFilled size={16} className={styles.iconWarning} />
          </span>
          <span className={styles.metricLabel}>{intl.formatMessage(messages.labelRunWithIssues)}</span>
        </div>
        <div className={styles.metricTile}>
          <span className={styles.metricValue}>
            {metrics.failed}<ErrorFilled size={16} className={styles.iconFailed} />
          </span>
          <span className={styles.metricLabel}>{intl.formatMessage(messages.labelFailed)}</span>
        </div>
        <div className={styles.metricTile}>
          <span className={styles.metricValue}>
            {metrics.cancelled}<Misuse size={16} className={styles.iconCancelled} />
          </span>
          <span className={styles.metricLabel}>{intl.formatMessage(messages.labelCancelled)}</span>
        </div>
      </div>
    </div>
  );
}
