import React, { useCallback, useMemo, useState } from 'react';
import {
  Button,
  Dropdown,
  OverflowMenu,
  OverflowMenuItem,
  Tag,
} from '@carbon/react';
import {
  Add,
  Renew,
  ErrorFilled,
  WarningFilled,
  InProgress,
} from '@carbon/icons-react';
import { useIntl } from 'react-intl';
import type { FlowRow, FlowRunStatus } from '@/types';
import { SharedDataTable, EditDetailsModal, DeleteModal } from '@/components/common';
import { messages } from './FlowsTable.messages';
import styles from './FlowsTable.module.scss';

interface FlowsTableProps {
  readonly rows: FlowRow[];
  readonly isLoading?: boolean;
  readonly onNewFlow: () => void;
  readonly onOpenFlow: (flowId: string) => void;
  readonly onOpenRuns: (flowId: string) => void;
  readonly onRefresh: () => void;
  readonly onEditFlow: (flowId: string, updates: { name: string; description: string; tags: string[] }) => Promise<void>;
  readonly onDeleteFlow: (flowId: string) => Promise<void>;
}

const MAX_VISIBLE_TAGS = 3;

/**
 * Renders the Tags cell: up to MAX_VISIBLE_TAGS blue chips, then a "+N" chip.
 */
function renderTagsCell(tags: string[]): React.JSX.Element {
  const visible = tags.slice(0, MAX_VISIBLE_TAGS);
  const overflow = tags.length - MAX_VISIBLE_TAGS;
  return (
    <div className={styles.tagsCell}>
      {visible.map((t) => <Tag key={t} type="blue" size="sm">{t}</Tag>)}
      {overflow > 0 && (
        <Tag type="gray" size="sm">+{overflow}</Tag>
      )}
    </div>
  );
}

/**
 * Renders the "Needs review" cell: each non-zero count shown with its icon inline.
 * e.g.  1 🔴  3 ⚠️  1 🌙
 * Shows "—" when there are no runs at all.
 */
function renderNeedsReviewCell(runStatus: FlowRunStatus | null, runCount: number | null): React.JSX.Element {
  if (!runCount || !runStatus) {
    return <span className={styles.needsReviewNone}>—</span>;
  }

  const hasAny = runStatus.errors > 0 || runStatus.warnings > 0 || runStatus.running > 0;
  if (!hasAny) {
    return <span className={styles.needsReviewNone}>—</span>;
  }

  return (
    <span className={styles.needsReviewCell}>
      {runStatus.errors > 0 && (
        <span className={styles.needsReviewItem}>
          {runStatus.errors}
          <ErrorFilled size={16} className={styles.iconError} />
        </span>
      )}
      {runStatus.warnings > 0 && (
        <span className={styles.needsReviewItem}>
          {runStatus.warnings}
          <WarningFilled size={16} className={styles.iconWarning} />
        </span>
      )}
      {runStatus.running > 0 && (
        <span className={styles.needsReviewItem}>
          {runStatus.running}
          <InProgress size={16} className={styles.iconRunning} />
        </span>
      )}
    </span>
  );
}

export function FlowsTable({
  rows,
  isLoading = false,
  onNewFlow,
  onOpenFlow,
  onOpenRuns,
  onRefresh,
  onEditFlow,
  onDeleteFlow,
}: FlowsTableProps): React.JSX.Element {
  const intl = useIntl();
  // Flow | Runs | Needs review | Tags | Last modified | Created on
  const tableHeaders = [
    { key: 'name',        header: intl.formatMessage(messages.headerFlow)         },
    { key: 'run_count',   header: intl.formatMessage(messages.headerRuns)         },
    { key: 'run_status',  header: intl.formatMessage(messages.headerNeedsReview)  },
    { key: 'tags',        header: intl.formatMessage(messages.headerTags)         },
    { key: 'modified_on', header: intl.formatMessage(messages.headerLastModified), isSortable: true },
    { key: 'created_on',  header: intl.formatMessage(messages.headerCreatedOn),    isSortable: true },
    { key: 'actions',     header: ''                                              },
  ];
  const statusOptions = [
    { id: 'all',      label: intl.formatMessage(messages.statusAll)      },
    { id: 'errors',   label: intl.formatMessage(messages.statusErrors)   },
    { id: 'warnings', label: intl.formatMessage(messages.statusWarnings) },
    { id: 'running',  label: intl.formatMessage(messages.statusRunning)  },
    { id: 'none',     label: intl.formatMessage(messages.statusNoRuns)   },
  ];
  const [statusFilter, setStatusFilter] = useState('all');
  const [deleteTarget, setDeleteTarget] = useState<FlowRow | null>(null);
  const [editTarget, setEditTarget] = useState<FlowRow | null>(null);

  const rowMap = useMemo(() => new Map(rows.map((flow) => [flow.flow_id, flow])), [rows]);

  const renderToolbarLeft = useCallback(() => (
    <div className={styles.toolbarLeft}>
      <span className={styles.statusLabel}>{intl.formatMessage(messages.statusLabel)}</span>
      <Dropdown
        id="flow-status-filter"
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
  ), [statusFilter, intl, statusOptions]);

  const renderToolbarActions = useCallback(() => (
    <>
      <Button
        kind="ghost"
        renderIcon={Renew}
        iconDescription={intl.formatMessage(messages.refreshDescription)}
        hasIconOnly
        tooltipPosition="bottom"
        onClick={onRefresh}
        disabled={isLoading}
      />
      <Button
        kind="primary"
        renderIcon={Add}
        onClick={onNewFlow}
        className={styles.newFlowButton}
      >
        {intl.formatMessage(messages.newFlow)}
      </Button>
    </>
  ), [isLoading, onNewFlow, onRefresh, intl]);

  // Note: `id`/`tagsSearch` are extra string fields folded in purely so
  // SharedDataTable's built-in search (which matches any string value in the
  // row) covers tags and run count too, matching the previous custom filter.
  // `renderCell` below overrides the visual rendering of every column anyway.
  const filteredRows = useMemo(() => rows
    .filter((flow) => {
      if (statusFilter === 'all') { return true; }
      if (statusFilter === 'none') { return !flow.run_count; }
      if (statusFilter === 'errors') { return (flow.run_status?.errors ?? 0) > 0; }
      if (statusFilter === 'warnings') { return (flow.run_status?.warnings ?? 0) > 0; }
      if (statusFilter === 'running') { return (flow.run_status?.running ?? 0) > 0; }
      return true;
    })
    .map((flow) => ({
      id: flow.flow_id,
      name: flow.name,
      run_count: String(flow.run_count ?? ''),
      // run_status is looked up from rowMap by renderCell — omitted here since
      // FlowRunStatus is not a valid ReactNode for SharedDataTableRow.
      run_status: null,
      tags: flow.tags.join(' '),
      modified_on: new Date(flow.modified_on).toLocaleDateString(),
      created_on: new Date(flow.created_on).toLocaleDateString(),
    })), [rows, statusFilter]);

  return (
    <div className={styles.tableWrapper}>
      <SharedDataTable
        headers={tableHeaders}
        rows={filteredRows}
        searchable
        searchPlaceholder={intl.formatMessage(messages.searchPlaceholder)}
        paginated={false}
        loading={isLoading}
        size="lg"
        sortRow={(_cellA, _cellB, { key, sortDirection, rowIds: [idA, idB] }) => {
          const rowA = rowMap.get(idA);
          const rowB = rowMap.get(idB);
          if (!rowA || !rowB) { return 0; }
          const timeA = key === 'modified_on' ? new Date(rowA.modified_on).getTime() : new Date(rowA.created_on).getTime();
          const timeB = key === 'modified_on' ? new Date(rowB.modified_on).getTime() : new Date(rowB.created_on).getTime();
          return sortDirection === 'ASC' ? timeA - timeB : timeB - timeA;
        }}
        renderToolbarLeft={renderToolbarLeft}
        renderToolbarActions={renderToolbarActions}
        renderCell={(cell, row) => {
          const original = rowMap.get(row.id);
          if (!original) { return undefined; }
          switch (cell.info.header) {
            case 'name':
              return (
                <Button
                  kind="ghost"
                  size="sm"
                  className={styles.nameLink}
                  onClick={() => { onOpenFlow(original.flow_id); }}
                >
                  {original.name}
                </Button>
              );
            case 'run_count':
              if (original.run_count === null) { return '—'; }
              return (
                <Button
                  kind="ghost"
                  size="sm"
                  className={styles.runLink}
                  onClick={() => { onOpenRuns(original.flow_id); }}
                >
                  {original.run_count}
                </Button>
              );
            case 'run_status':
              return renderNeedsReviewCell(original.run_status, original.run_count);
            case 'tags':
              return renderTagsCell(original.tags);
            case 'actions':
              return (
                 <OverflowMenu
                   size="sm"
                   flipped
                   iconDescription={intl.formatMessage(messages.rowActionsDescription)}
                   selectorPrimaryFocus=".cds--overflow-menu-options__option"
                 >
                   <OverflowMenuItem
                     itemText={intl.formatMessage(messages.actionEditDetails)}
                     onClick={() => { setEditTarget(original); }}
                   />
                   <OverflowMenuItem
                     itemText={intl.formatMessage(messages.actionViewFlow)}
                     onClick={() => { onOpenFlow(original.flow_id); }}
                   />
                   <OverflowMenuItem
                     itemText={intl.formatMessage(messages.actionDelete)}
                     isDelete
                     hasDivider
                     onClick={() => { setDeleteTarget(original); }}
                   />
                 </OverflowMenu>
               );
            default:
              return undefined;
          }
        }}
      />

      <EditDetailsModal
        open={editTarget !== null}
        title={intl.formatMessage(messages.editFlowTitle)}
        initialValues={{
          name: editTarget?.name ?? '',
          description: editTarget?.description ?? '',
          tags: editTarget?.tags ?? [],
        }}
        onCancel={() => { setEditTarget(null); }}
        onEdit={(updates) =>
          onEditFlow(editTarget?.flow_id ?? '', updates).then(() => {
            setEditTarget(null);
          })
        }
      />

      <DeleteModal
        open={deleteTarget !== null}
        assetType="Flow"
        assetName={deleteTarget?.name ?? ''}
        onCancel={() => { setDeleteTarget(null); }}
        onDelete={() => {
          if (!deleteTarget) { return Promise.resolve(); }
          return onDeleteFlow(deleteTarget.flow_id).then(() => {
            setDeleteTarget(null);
          });
        }}
      />
    </div>
  );
}
