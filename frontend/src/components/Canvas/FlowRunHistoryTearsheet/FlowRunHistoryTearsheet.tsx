import React, { useCallback, useEffect, useState } from 'react';
import { Button } from '@carbon/react';
import { Download } from '@carbon/icons-react';
import { NoDataEmptyState } from '@carbon/ibm-products';
import { useNavigate } from 'react-router-dom';
import { useIntl } from 'react-intl';
import { SharedDataTable, SharedTearsheet } from '@/components/common';
import { DOWNLOAD_ENABLED_STATUSES } from '@/constants/flowRunHistory';
import type { SharedDataTableHeader } from '@/components/common/SharedDataTable';
import { API_STATUS_MAP } from '@/constants/flowStatus';
import { getJobRuns } from '@/services/api';
import { getJobRun } from '@/services/api/actions/job-run-actions';
import { generateRoute } from '@/config';
import type { JobRunListItem } from '@/types';
import { StatusIcon } from '@/components/FlowDetail';
import type { RunStatus } from '@/components/FlowDetail';
import { JOB_RUN_STATUS } from '@/constants/jobRunStatus';
import { formatEpochToDisplay, formatElapsedTime } from '@/utils/dateTimeUtils';
import { useTheme } from '@/hooks';
import { messages } from './FlowRunHistoryTearsheet.messages';
import styles from './FlowRunHistoryTearsheet.module.scss';

export interface FlowRunHistoryTearsheetProps {
  open: boolean;
  onClose: () => void;
  /** Flow ID used to fetch job runs. When undefined, the table stays empty. */
  flowId?: string;
  /** project_id query param carried through to the run details URL. */
  projectId?: string;
}

/** Long-form locale options for tearsheet timestamp display (e.g. "August 5, 2024 at 6:26 AM"). */
const TIMESTAMP_OPTIONS: Intl.DateTimeFormatOptions = {
  year: 'numeric',
  month: 'long',
  day: 'numeric',
  hour: 'numeric',
  minute: '2-digit',
  hour12: true,
};

/**
 * Downloads execution logs for a job run as a `.txt` file.
 * Fetches with include_logs=true, concatenates per-node log strings from
 * node_sequence, and saves the result as a text file.
 */
function triggerDownloadLogs(runId: string, timestamp: string): void {
  void getJobRun(runId, true).then((res) => {
    const data = res.data as { node_sequence?: string[]; error_logs?: string } & Record<string, unknown>;
    let logs = '';

    if (data.node_sequence?.length) {
      data.node_sequence.forEach((nodeId) => {
        const nodeLog = data[nodeId];
        if (typeof nodeLog === 'string') { logs += nodeLog; }
      });
    } else {
      logs = JSON.stringify(data, null, 2);
    }

    if (data.error_logs && typeof data.error_logs === 'string') {
      logs += `\nError stack trace:\n${data.error_logs}`;
    }

    const blob = new Blob([logs], { type: 'text/plain' });
    const link = document.createElement('a');
    link.href = URL.createObjectURL(blob);
    link.download = `${timestamp}_log.txt`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(link.href);
  });
}

export function FlowRunHistoryTearsheet({
  open,
  onClose,
  flowId,
  projectId = '',
}: FlowRunHistoryTearsheetProps): React.JSX.Element {
  const intl = useIntl();

  const statusLabels: Record<string, string> = {
    run:             intl.formatMessage(messages.statusCompleted),
    in_progress:     intl.formatMessage(messages.statusInProgress),
    run_with_issues: intl.formatMessage(messages.statusRunWithIssues),
    failed:          intl.formatMessage(messages.statusFailed),
    cancelled:       intl.formatMessage(messages.statusCanceled),
  };

  // Overrides for status strings whose display label differs from the raw API value.
  // All other statuses are already human-readable and fall back to the raw string.
  const rawStatusLabelOverrides: Partial<Record<string, string>> = {
    [JOB_RUN_STATUS.COMPLETED_WITH_ERRORS]:   intl.formatMessage(messages.statusCompletedWithErrors),
    [JOB_RUN_STATUS.COMPLETED_WITH_WARNINGS]: intl.formatMessage(messages.statusCompletedWithWarnings),
  };

  const tableHeaders: SharedDataTableHeader[] = [
    { key: 'timestamp', header: intl.formatMessage(messages.headerTimestamp) },
    { key: 'status',    header: intl.formatMessage(messages.headerStatus)    },
    { key: 'duration',  header: intl.formatMessage(messages.headerDuration)  },
    { key: 'logs',      header: intl.formatMessage(messages.headerLogs)      },
  ];

  const navigate = useNavigate();
  const { isDarkMode } = useTheme();
  const [rawItems, setRawItems] = useState<JobRunListItem[]>([]);
  const [loading, setLoading] = useState(false);

  const fetchRuns = useCallback((): void => {
    if (!flowId) { return; }
    setLoading(true);
    getJobRuns({ job_id: flowId })
      .then((res) => {
        setRawItems(res.data.list);
      })
      .catch(() => {
        // Non-fatal: keep existing rows on error.
      })
      .finally(() => {
        setLoading(false);
      });
  }, [flowId]);

  // Fetch whenever the tearsheet opens or the flowId changes.
  useEffect(() => {
    if (open && flowId) {
      fetchRuns();
    }
  }, [open, flowId, fetchRuns]);

  // Build rows — timestamp is a clickable link navigating to the run details page.
  const rows = rawItems.map((item) => {
    const timestamp = formatEpochToDisplay(item.start_time, TIMESTAMP_OPTIONS) || '—';
    const canDownload = DOWNLOAD_ENABLED_STATUSES.has(item.status);
    const uiStatus = (API_STATUS_MAP[item.status] ?? null) as RunStatus | null;
    return {
      id: item.job_run_id,
      timestamp: (
        <button
          type="button"
          className={styles.timestampLink}
          onClick={() => {
            if (flowId) {
              onClose();
              void navigate(generateRoute.runDetails(flowId, item.job_run_id, projectId));
            }
          }}
        >
          {timestamp}
        </button>
      ),
      status: uiStatus ? (
        <span className={styles.statusCell}>
          <StatusIcon status={uiStatus} iconStyles={styles} />
          {statusLabels[uiStatus]}
        </span>
      ) : (rawStatusLabelOverrides[item.status] ?? item.status),
      duration: formatElapsedTime(item.duration),
      logs: canDownload ? (
        <Button
          kind="ghost"
          size="sm"
          renderIcon={Download}
          iconDescription={intl.formatMessage(messages.downloadLogsDescription)}
          hasIconOnly
          onClick={() => { triggerDownloadLogs(item.job_run_id, timestamp); }}
        />
      ) : null,
    };
  });

  const emptyState = (
    <NoDataEmptyState
      illustrationTheme={isDarkMode ? 'dark' : 'light'}
      illustrationPosition="top"
      size="sm"
      title={intl.formatMessage(messages.emptyTitle)}
      subtitle={intl.formatMessage(messages.emptySubtitle)}
    />
  );

  return (
    <SharedTearsheet
      open={open}
      onClose={onClose}
      title={intl.formatMessage(messages.title)}
      hideFooter
    >
      <div className={styles.tearsheetContent}>
        <SharedDataTable
          headers={tableHeaders}
          rows={rows}
          loading={loading}
          emptyState={emptyState}
        />
      </div>
    </SharedTearsheet>
  );
}
