import React, { useMemo, useState } from 'react';
import {
  Button,
  Dropdown,
  OverflowMenu,
  OverflowMenuItem,
} from '@carbon/react';
import {
  Renew,
  CheckmarkFilled,
  InProgress,
  WarningFilled,
  ErrorFilled,
  Misuse,
} from '@carbon/icons-react';
import { useIntl } from 'react-intl';
import { SharedDataTable } from '@/components/common/SharedDataTable';
import { messages } from './FlowRunsTable.messages';
import styles from './FlowRunsTable.module.scss';

// ─── Types ────────────────────────────────────────────────────────────────────

/**
 * UI status of a single job run, derived from the API status string via
 * `API_STATUS_MAP` in `FlowDetail.tsx`.
 *
 * | Value             | API statuses mapped                                      |
 * |-------------------|----------------------------------------------------------|
 * | `run`             | Completed                                                |
 * | `in_progress`     | Queued, Pending, Starting, Running, Resuming, Paused, Canceling |
 * | `run_with_issues` | CompletedWithWarnings, CompletedWithErrors               |
 * | `failed`          | Failing, Failed, Aborted                                 |
 * | `cancelled`       | Canceled                                                 |
 */
export type RunStatus = 'run' | 'in_progress' | 'run_with_issues' | 'failed' | 'cancelled';

/**
 * A single row in the {@link FlowRunsTable}.
 * Derived from `JobRunListItem` in `FlowDetail.fetchRuns` — timestamps and
 * durations are pre-formatted before being stored here.
 */
export interface RunRow {
  /** Job run UUID — used as the DataTable row `id` and for delete calls. */
  run_id: string;
  /** Formatted start time string (locale date + time), e.g. `"8/5/2026, 6:26:05 AM"`. */
  start_time: string;
  /** Raw start time epoch in seconds/milliseconds for accurate sorting. */
  start_time_epoch?: number;
  /** UI status category derived from the API status string. */
  status: RunStatus;
  /** Formatted elapsed duration string, e.g. `"00:02:34"`. */
  duration: string;
  /** Raw duration in seconds for accurate sorting. */
  duration_seconds?: number;
}

// ─── StatusIcon ───────────────────────────────────────────────────────────────

export function StatusIcon({ status, iconStyles }: { status: RunStatus; iconStyles: Record<string, string> }): React.JSX.Element {
  switch (status) {
    case 'run':             return <CheckmarkFilled size={16} className={iconStyles.iconRun} />;
    case 'in_progress':     return <InProgress     size={16} className={iconStyles.iconProgress} />;
    case 'run_with_issues': return <WarningFilled   size={16} className={iconStyles.iconWarning} />;
    case 'failed':          return <ErrorFilled     size={16} className={iconStyles.iconFailed} />;
    case 'cancelled':       return <Misuse          size={16} className={iconStyles.iconCancelled} />;
  }
}

// ─── Props ────────────────────────────────────────────────────────────────────

interface FlowRunsTableProps {
  /** Run rows to display — pre-mapped from the job-runs API response. */
  readonly runs: RunRow[];
  /**
   * When `true`, renders a `DataTableSkeleton` shaped like the final toolbar/table
   * instead of the table itself — covers both the initial fetch and a manual
   * Refresh, so stale cached rows are never shown alongside a loading indicator.
   * Also disables the Refresh button.
   */
  readonly isLoading: boolean;
  /** Called when the user clicks the Refresh button in the toolbar. */
  readonly onRefresh: () => void;
  /**
   * Called when the user clicks "Delete" on a completed/failed run.
   * Receives the full `RunRow` so the parent can show a confirmation modal.
   * Not called for in-progress runs (the overflow shows "Cancel run" instead).
   */
  readonly onDeleteRun: (run: RunRow) => void;
  /** Called when the user clicks "Cancel run" on an in-progress run. */
  readonly onCancelRun: (runId: string) => void;
  /** Called when the user clicks "View run" or the start time link. */
  readonly onViewRun: (runId: string) => void;
}

/**
 * Data table listing job runs for the current flow. Built on {@link SharedDataTable}.
 *
 * Owns `statusFilter` state internally — the Status dropdown filters the visible
 * rows without triggering a new API call. Callers provide data and side-effect
 * callbacks only.
 *
 * Columns: Start time · Status · Duration · Actions (overflow menu)
 */
export function FlowRunsTable({
  runs,
  isLoading,
  onRefresh,
  onDeleteRun,
  onCancelRun,
  onViewRun,
}: FlowRunsTableProps): React.JSX.Element {
  const intl = useIntl();

  const STATUS_LABELS: Record<RunStatus, string> = {
    run:             intl.formatMessage(messages.statusCompleted),
    in_progress:     intl.formatMessage(messages.statusInProgress),
    run_with_issues: intl.formatMessage(messages.statusRunWithIssues),
    failed:          intl.formatMessage(messages.statusFailed),
    cancelled:       intl.formatMessage(messages.statusCanceled),
  };

  const tableHeaders = [
    { key: 'start_time', header: intl.formatMessage(messages.headerStartTime), isSortable: true },
    { key: 'status',     header: intl.formatMessage(messages.headerStatus)     },
    { key: 'duration',   header: intl.formatMessage(messages.headerDuration),  isSortable: true },
    { key: 'actions',    header: ''                                            },
  ];

  const statusOptions = [
    { id: 'all',             label: intl.formatMessage(messages.statusAll)            },
    { id: 'run',             label: intl.formatMessage(messages.statusCompleted)      },
    { id: 'in_progress',     label: intl.formatMessage(messages.statusInProgress)     },
    { id: 'run_with_issues', label: intl.formatMessage(messages.statusRunWithIssues)  },
    { id: 'failed',          label: intl.formatMessage(messages.statusFailed)         },
    { id: 'cancelled',       label: intl.formatMessage(messages.statusCanceled)       },
  ];

  const [statusFilter, setStatusFilter] = useState('all');

  const rowMap = useMemo(() => new Map(runs.map((r) => [r.run_id, r])), [runs]);

  const filteredRows = useMemo(() => {
    // Default sort: Start time descending (most recent run first)
    const sorted = [...runs].sort((a, b) => {
      const timeA = a.start_time_epoch ?? 0;
      const timeB = b.start_time_epoch ?? 0;
      return timeB - timeA;
    });

    return sorted
      .filter((r) => statusFilter === 'all' || r.status === statusFilter)
      .map((r) => ({
        id: r.run_id,
        start_time: r.start_time,
        // status rendered via StatusIcon + label in renderCell — kept as a plain
        // string here so SharedDataTable's built-in search can still match it.
        status: STATUS_LABELS[r.status],
        duration: r.duration,
      }));
  }, [runs, statusFilter]);

  return (
    <div className={styles.tableWrapper}>
      <SharedDataTable
        headers={tableHeaders}
        rows={filteredRows}
        searchable
        searchPlaceholder={intl.formatMessage(messages.searchPlaceholder)}
        loading={isLoading}
        size="lg"
        sortRow={(_cellA, _cellB, { key, sortDirection, rowIds: [idA, idB] }) => {
          const rowA = rowMap.get(idA);
          const rowB = rowMap.get(idB);
          if (!rowA || !rowB) { return 0; }
          let valA = 0;
          let valB = 0;
          if (key === 'start_time') {
            valA = rowA.start_time_epoch ?? 0;
            valB = rowB.start_time_epoch ?? 0;
          } else if (key === 'duration') {
            valA = rowA.duration_seconds ?? 0;
            valB = rowB.duration_seconds ?? 0;
          }
          return sortDirection === 'ASC' ? valA - valB : valB - valA;
        }}
        renderToolbarLeft={() => (
          <div className={styles.toolbarLeft}>
            <span className={styles.statusLabel}>{intl.formatMessage(messages.statusFilterLabel)}</span>
            <Dropdown
              id="run-status-filter"
              label={intl.formatMessage(messages.statusAll)}
              titleText=""
              hideLabel
              items={statusOptions}
              itemToString={(item) => item?.label ?? ''}
              selectedItem={statusOptions.find((o) => o.id === statusFilter) ?? statusOptions[0]}
              onChange={({ selectedItem }) => { setStatusFilter(selectedItem?.id ?? 'all'); }}
              className={styles.statusDropdown}
            />
          </div>
        )}
        renderToolbarActions={() => (
          <Button
            kind="ghost"
            renderIcon={Renew}
            iconDescription={intl.formatMessage(messages.refreshDescription)}
            hasIconOnly
            tooltipPosition="bottom"
            disabled={isLoading}
            onClick={onRefresh}
          />
        )}
        renderCell={(cell, row) => {
          const original = rowMap.get(row.id);
          if (!original) { return undefined; }
          const isInProgress = original.status === 'in_progress';
          switch (cell.info.header) {
            case 'start_time':
              return (
                <Button
                  kind="ghost"
                  size="sm"
                  className={styles.startTimeLink}
                  onClick={() => { onViewRun(original.run_id); }}
                >
                  {original.start_time}
                </Button>
              );
            case 'status':
              return (
                <span className={styles.statusCell}>
                  <StatusIcon status={original.status} iconStyles={styles} />
                  {STATUS_LABELS[original.status]}
                </span>
              );
            case 'actions':
              return (
                 <OverflowMenu
                   size="sm"
                   flipped
                   iconDescription={intl.formatMessage(messages.rowActionsDescription)}
                   selectorPrimaryFocus=".cds--overflow-menu-options__option"
                 >
                   <OverflowMenuItem
                     itemText={intl.formatMessage(messages.actionViewRun)}
                     onClick={() => { onViewRun(original.run_id); }}
                   />
                   {isInProgress ? (
                     <OverflowMenuItem
                       itemText={intl.formatMessage(messages.actionCancelRun)}
                       isDelete
                       hasDivider
                       onClick={() => { onCancelRun(original.run_id); }}
                     />
                   ) : (
                     <OverflowMenuItem
                       itemText={intl.formatMessage(messages.actionDelete)}
                       isDelete
                       hasDivider
                       onClick={() => { onDeleteRun(original); }}
                     />
                   )}
                 </OverflowMenu>
               );
            default:
              return undefined;
          }
        }}
      />
    </div>
  );
}
