/**
 * @fileoverview Node summary component displaying node metadata and execution details.
 * Shows node label, operator type, status badge, execution time, and metadata table.
 *
 * Layout:
 *  - DocumentExport icon in header
 *  - Carbon DataTable with Name/Value column headers
 *  - node_status key filtered from metadata rows (already shown in the status badge)
 *  - Skipped Docs / Failed Docs arrays shown as clickable count → tearsheet
 */

import React, { useMemo, useState } from 'react';
import {
  CheckmarkFilled,
  ErrorFilled,
  WarningFilled,
  InProgress,
  CircleDash,
  DocumentExport,
  View,
  Download,
} from '@carbon/icons-react';
import type { CarbonIconType } from '@carbon/icons-react';
import {
  Button,
  DataTable,
  Table,
  TableHead,
  TableRow,
  TableHeader,
  TableBody,
  TableCell,
  Tooltip,
} from '@carbon/react';
import { useIntl } from 'react-intl';
import type { NodeMetadataItem, JobStats } from '@/types';
import { JOB_RUN_STATUS } from '@/constants/jobRunStatus';
import {
  CELL_VALUE_MAX_LENGTH,
  CELL_VALUE_FLOAT_DECIMALS,
  CELL_VALUE_FLOAT_THRESHOLD,
  DEFAULT_NODE_STATUS,
} from '@/constants/runSidePanel';
import { SharedDataTable, SharedTearsheet } from '@/components/common';
import { messages } from './NodeSummary.messages';
import styles from './NodeSummary.module.scss';

// ─── Doc array item shape ─────────────────────────────────────────────────────

interface DocItem {
  id: string;
  fileName: string;
  reason: string;
}

interface NodeSummaryProps {
  nodeMetadata: NodeMetadataItem;
  jobStats: JobStats;
}

/** Typed row shape accepted by MetadataDataTable. */
interface MetadataRow {
  id: string;
  name: string;
  value: React.ReactNode;
}

// Keys that should never appear as metadata table rows — they're shown elsewhere
const FILTERED_METADATA_KEYS = new Set(['node_status', 'node_id', 'nodeId', 'id', 'ID']);

/**
 * Convert snake_case / lower_case keys to Title Case with spaces.
 *   "documents_in_scope" → "Documents In Scope"
 *   "failed_docs_count"  → "Failed Docs Count"
 */
function formatColumnHeader(key: string): string {
  return key
    .split('_')
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1).toLowerCase())
    .join(' ');
}

/**
 * Format a numeric value for display.
 * Floats below {@link CELL_VALUE_FLOAT_THRESHOLD} are rounded to {@link CELL_VALUE_FLOAT_DECIMALS} decimal places.
 */
function formatNumericValue(value: number): string {
  if (!Number.isInteger(value) && Math.abs(value) < CELL_VALUE_FLOAT_THRESHOLD) {
    return String(Number(value.toFixed(CELL_VALUE_FLOAT_DECIMALS)));
  }
  return String(value);
}

/**
 * Truncate a long string with an ellipsis and wrap in a Carbon Tooltip so the
 * full value is visible on hover.
 */
function truncateWithTooltip(text: string): React.ReactNode {
  if (text.length <= CELL_VALUE_MAX_LENGTH) { return text; }
  const truncated = `${text.slice(0, CELL_VALUE_MAX_LENGTH)}...`;
  return (
    <Tooltip align="top" label={text}>
      <span>{truncated}</span>
    </Tooltip>
  );
}

/**
 * Format a cell value for display:
 *  - Arrays/objects → JSON string, truncated with tooltip if > 100 chars
 *  - Floats (non-integer, < 1000) → 4 decimal places
 *  - Long strings → truncated with tooltip at 100 chars
 */
function formatCellValue(_key: string, value: unknown): React.ReactNode {
  if (value === null || value === undefined) { return ''; }

  if (typeof value === 'number') { return formatNumericValue(value); }

  // Arrays and objects — serialize to JSON then truncate
  if (typeof value === 'object') {
    return truncateWithTooltip(JSON.stringify(value));
  }

  return truncateWithTooltip(String(value));
}

/**
 * Parse a raw doc array value from node_metadata into a typed DocItem[].
 * Handles both {id, name, reason} and {id, file_name, reason} shapes.
 */
function parseDocArray(raw: unknown): DocItem[] {
  if (!Array.isArray(raw)) { return []; }
  return raw
    .filter((item): item is Record<string, unknown> => typeof item === 'object' && item !== null)
    .map((item) => ({
      id: String(item.id ?? item.document_id ?? ''),
      fileName: String(item.name ?? item.file_name ?? item.fileName ?? ''),
      reason: String(item.reason ?? ''),
    }));
}

/** Download a doc array as JSON. */
function downloadDocs(docs: DocItem[], filename: string): void {
  const blob = new Blob([JSON.stringify(docs, null, 2)], { type: 'application/json' });
  const link = document.createElement('a');
  link.href = URL.createObjectURL(blob);
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(link.href);
}

/**
 * Compute the CSS class for the status badge by stripping spaces only (preserve PascalCase).
 * e.g. "In Progress" → styles.statusInProgress
 */
function getStatusClass(nodeStatus: string): string {
  const key = `status${nodeStatus.replace(/\s+/g, '')}`;
  return (styles as Record<string, string>)[key] ?? (styles.statusNotStarted as string) ?? '';
}

/**
 * Returns the Carbon icon component for a given node status.
 */
function getStatusIconComponent(status: string): CarbonIconType | null {
  const s = status.toLowerCase().replace(/\s+/g, '');
  if (s === JOB_RUN_STATUS.COMPLETED.toLowerCase() || s === 'succeeded') {
    return CheckmarkFilled;
  }
  if (s === JOB_RUN_STATUS.FAILED.toLowerCase()) { return ErrorFilled; }
  if (s === 'warning' || s === 'completedwitherrors' || s === 'completedwithwarnings') {
    return WarningFilled;
  }
  if (
    s === JOB_RUN_STATUS.RUNNING.toLowerCase() ||
    s === JOB_RUN_STATUS.STARTING.toLowerCase() ||
    s === JOB_RUN_STATUS.CANCELING.toLowerCase()
  ) { return InProgress; }
  if (
    s === 'notstarted' ||
    s === 'queued' ||
    s === JOB_RUN_STATUS.PENDING.toLowerCase() ||
    s === JOB_RUN_STATUS.CANCELED.toLowerCase() ||
    s === JOB_RUN_STATUS.SKIPPED.toLowerCase()
  ) { return CircleDash; }
  return null;
}

/**
 * Renders a Carbon DataTable for a list of name/value metadata rows.
 */
function MetadataDataTable({ rows }: { rows: MetadataRow[] }): React.JSX.Element {
  const intl = useIntl();
  const dtRows = rows as unknown as React.ComponentProps<typeof DataTable>['rows'];
  const metadataTableHeaders = [
    { key: 'name',  header: intl.formatMessage(messages.metadataHeaderName)  },
    { key: 'value', header: intl.formatMessage(messages.metadataHeaderValue) },
  ];
  return (
    <DataTable rows={dtRows} headers={metadataTableHeaders}>
      {/* eslint-disable react/jsx-props-no-spreading, react/jsx-key */}
      {({ rows: tableRows, headers, getHeaderProps, getRowProps }) => (
        <Table className={styles.metadataTable}>
          <TableHead>
            <TableRow>
              {headers.map((header) => (
                <TableHeader {...getHeaderProps({ header })} className={styles.tableHeader}>
                  {header.header}
                </TableHeader>
              ))}
            </TableRow>
          </TableHead>
          <TableBody>
            {tableRows.map((row) => (
              <TableRow {...getRowProps({ row })}>
                {row.cells.map((cell) => (
                  <TableCell key={cell.id}>{cell.value}</TableCell>
                ))}
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
      {/* eslint-enable react/jsx-props-no-spreading, react/jsx-key */}
    </DataTable>
  );
}

// ─── DocsTearsheet ────────────────────────────────────────────────────────────

interface DocsTearsheetProps {
  open: boolean;
  title: string;
  docs: DocItem[];
  downloadFilename: string;
  onClose: () => void;
}

function DocsTearsheet({ open, title, docs, downloadFilename, onClose }: DocsTearsheetProps): React.JSX.Element {
  const intl = useIntl();
  const docTableHeaders = [
    { key: 'documentId', header: intl.formatMessage(messages.documentIdHeader) },
    { key: 'fileName',   header: intl.formatMessage(messages.fileNameHeader)   },
    { key: 'reason',     header: intl.formatMessage(messages.reasonHeader)     },
  ];
  const rows = docs.map((doc) => ({
    id: doc.id || `doc-${doc.fileName}`,
    documentId: doc.id,
    fileName: doc.fileName,
    reason: doc.reason,
  }));

  return (
    <SharedTearsheet
      open={open}
      onClose={onClose}
      title={title}
      hideFooter
    >
      <div className={styles.tearsheetContent}>
        <SharedDataTable
          headers={docTableHeaders}
          rows={rows}
          searchable
          searchPlaceholder={intl.formatMessage(messages.searchDocuments)}
          renderToolbarActions={() => (
            <Button
              kind="primary"
              size="md"
              renderIcon={Download}
              onClick={() => { downloadDocs(docs, downloadFilename); }}
            >
              {intl.formatMessage(messages.download)}
            </Button>
          )}
        />
      </div>
    </SharedTearsheet>
  );
}

// ─── NodeSummary ──────────────────────────────────────────────────────────────

export function NodeSummary({
  nodeMetadata,
  jobStats,
}: NodeSummaryProps): React.JSX.Element {
  const intl = useIntl();
  const [skippedDocsOpen, setSkippedDocsOpen] = useState(false);
  const [failedDocsOpen, setFailedDocsOpen] = useState(false);

  const nodeStat = useMemo(
    () => jobStats.node_stats[nodeMetadata.id],
    [nodeMetadata.id, jobStats.node_stats]
  );

  // DEFAULT_NODE_STATUS drives the CSS class and icon lookup.
  const nodeStatus = nodeStat?.node_status ?? DEFAULT_NODE_STATUS;
  const statusBadgeClass = `${styles.nodeStatus} ${getStatusClass(nodeStatus)}`;
  const StatusIcon = getStatusIconComponent(nodeStatus);
  const nodeStatusLabel = nodeStat?.node_status ?? intl.formatMessage(messages.statusNotStarted);

  // Parse doc arrays from node_metadata once
  const skippedDocs = useMemo(
    () => parseDocArray(nodeMetadata.node_metadata?.['skipped_docs']),
    [nodeMetadata.node_metadata]
  );
  const failedDocs = useMemo(
    () => parseDocArray(nodeMetadata.node_metadata?.['failed_docs']),
    [nodeMetadata.node_metadata]
  );

  // Metadata rows — filter out keys shown elsewhere, format names to Title Case.
  // Doc array keys → show count (clickable if > 0); other values → formatted string.
  const metadataRows = useMemo((): MetadataRow[] => {
    if (!nodeMetadata.node_metadata) { return []; }
    return Object.entries(nodeMetadata.node_metadata)
      .filter(([key]) => !FILTERED_METADATA_KEYS.has(key))
      .map(([key, value]) => {
        const label = formatColumnHeader(key);

        if (key === 'skipped_docs' && Array.isArray(value)) {
          const count = skippedDocs.length;
          return {
            id: key,
            name: label,
            value: count > 0 ? (
              <div className={styles.clickableDocCount}>
                <button
                  type="button"
                  data-testid="skipped-docs-count"
                  className={styles.docCountLink}
                  onClick={() => { setSkippedDocsOpen(true); }}
                >
                  {count}
                </button>
                <Button
                  kind="ghost"
                  size="sm"
                  renderIcon={View}
                  iconDescription={intl.formatMessage(messages.viewSkippedDocs)}
                  hasIconOnly
                  className={styles.viewDocsButton}
                  onClick={() => { setSkippedDocsOpen(true); }}
                />
              </div>
            ) : String(count),
          };
        }

        if (key === 'failed_docs' && Array.isArray(value)) {
          const count = failedDocs.length;
          return {
            id: key,
            name: label,
            value: count > 0 ? (
              <div className={styles.clickableDocCount}>
                <button
                  type="button"
                  data-testid="failed-docs-count"
                  className={styles.docCountLink}
                  onClick={() => { setFailedDocsOpen(true); }}
                >
                  {count}
                </button>
                <Button
                  kind="ghost"
                  size="sm"
                  renderIcon={View}
                  iconDescription={intl.formatMessage(messages.viewFailedDocs)}
                  hasIconOnly
                  className={styles.viewDocsButton}
                  onClick={() => { setFailedDocsOpen(true); }}
                />
              </div>
            ) : String(count),
          };
        }

        return {
          id: key,
          name: label,
          value: formatCellValue(key, value),
        };
      });
  }, [nodeMetadata.node_metadata, skippedDocs, failedDocs]);

  return (
    <div className={styles.nodeSummaryContainer}>
      {/* Header: DocumentExport icon + node name + status badge */}
      <div className={styles.nodeSummaryHeader}>
        <div className={styles.titleRow}>
          <DocumentExport className={styles.nodeIcon} />
          <div className={styles.titleContainer}>
            <h3 className={styles.nodeTitle}>{nodeStat?.name ?? nodeMetadata.operator}</h3>
            <div className={styles.nodeType}>{nodeMetadata.operator}</div>
          </div>
          <div className={statusBadgeClass}>
            {StatusIcon && <StatusIcon className={styles.statusIcon} />}
            {nodeStatusLabel}
          </div>
        </div>
      </div>

      {/* Content */}
      <div className={styles.nodeSummaryContent}>

        {/* Node Metadata — filtered properties from the metadata object */}
        {metadataRows.length > 0 && (
          <>
            <div className={styles.sectionHeader}>
              <span className={styles.sectionTitle}>{intl.formatMessage(messages.nodeSectionTitle)}</span>
            </div>
            <MetadataDataTable rows={metadataRows} />
          </>
        )}

        {!nodeStat && metadataRows.length === 0 && (
          <p className={styles.nodeDescription}>{intl.formatMessage(messages.noMetadata)}</p>
        )}
      </div>

      {/* Skipped Docs Tearsheet */}
      <DocsTearsheet
        open={skippedDocsOpen}
        title={intl.formatMessage(messages.skippedDocsTearsheetTitle)}
        docs={skippedDocs}
        downloadFilename="skipped_documents.json"
        onClose={() => { setSkippedDocsOpen(false); }}
      />

      {/* Failed Docs Tearsheet */}
      <DocsTearsheet
        open={failedDocsOpen}
        title={intl.formatMessage(messages.failedDocsTearsheetTitle)}
        docs={failedDocs}
        downloadFilename="failed_documents.json"
        onClose={() => { setFailedDocsOpen(false); }}
      />
    </div>
  );
}
