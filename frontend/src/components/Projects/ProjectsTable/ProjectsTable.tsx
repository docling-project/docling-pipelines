import React, { useMemo, useState } from 'react';
import type { ProjectRow } from '@/types';
import { Button, OverflowMenu, OverflowMenuItem, Tag } from '@carbon/react';
import { Add, Renew } from '@carbon/icons-react';
import { useIntl } from 'react-intl';
import { SharedDataTable, EditDetailsModal, DeleteModal } from '@/components/common';
import { messages } from './ProjectsTable.messages';
import styles from './ProjectsTable.module.scss';

/**
 * Props for {@link ProjectsTable}.
 */
interface ProjectsTableProps {
  /** The list of projects to display. Pass an empty array to show no rows. */
  readonly rows: ProjectRow[];
  /**
   * When `true`, renders a `DataTableSkeleton` shaped like the final toolbar/table
   * instead of the table itself — covers both the initial fetch and a manual
   * Refresh, so stale cached rows are never shown alongside a loading indicator.
   */
  readonly isLoading?: boolean;
  /** Called when the user clicks the "New project" toolbar button. */
  readonly onNewProject: () => void;
  /**
   * Called when the user clicks a project name link or "View project" in the overflow menu.
   * @param projectId - The `id` of the selected project.
   */
  readonly onOpenProject: (projectId: string) => void;
  /**
   * Called when the user clicks the Refresh icon button in the toolbar.
   * Triggers a re-fetch of the project list from `GET /api/projects`.
   */
  readonly onRefresh: () => void;
  /**
   * Called after the user confirms deletion in {@link DeleteModal}.
   * Must return a Promise — forwarded to the modal to drive its loading state.
   * @param projectId - The `id` of the project to delete.
   */
  readonly onDeleteProject: (projectId: string) => Promise<void>;
  /**
   * Called after the user saves changes in {@link EditDetailsModal}.
   * Must return a Promise — forwarded to the modal to drive its loading state.
   * @param id      - The `id` of the project being updated.
   * @param updates - The new name, description, and tags.
   */
  readonly onEditProject: (id: string, updates: { name: string; description: string; tags: string[] }) => Promise<void>;
}

/** Maximum number of tag chips to render inline before showing a `+N` badge. */
const MAX_VISIBLE_TAGS = 3;

/**
 * Renders the tags cell: up to {@link MAX_VISIBLE_TAGS} blue chips, then a `+N` badge.
 * Extracted to module scope — has no dependency on component state or props.
 *
 * @param tags - The full array of tag strings for the row.
 * @returns A `<div>` containing tag chips and an optional overflow count badge.
 */
function renderTagsCell(tags: string[]): React.JSX.Element {
  const visible = tags.slice(0, MAX_VISIBLE_TAGS);
  const overflow = tags.length - MAX_VISIBLE_TAGS;
  return (
    <div className={styles.tagsCell}>
      {visible.map((t) => (
        <Tag key={t} type="blue" size="sm">
          {t}
        </Tag>
      ))}
      {overflow > 0 && (
        <span className={styles.tagsOverflow}>+{overflow}</span>
      )}
    </div>
  );
}

/**
 * Searchable data table for the projects list. Built on {@link SharedDataTable}.
 *
 * Features:
 * - Persistent toolbar search (client-side, filters by project name via `SharedDataTable`).
 * - Refresh icon button and primary "New project" button (toolbar-right).
 * - Tags cell: up to {@link MAX_VISIBLE_TAGS} chips inline, then a `+N` overflow badge.
 * - Per-row overflow menu: Edit project, View project, Delete.
 * - {@link EditDetailsModal} and {@link DeleteModal} rendered as siblings.
 *
 * @remarks
 * Pagination is disabled (`paginated={false}`) — this table has always shown its
 * full row set inline, matching prior behavior.
 */
export function ProjectsTable({
  rows,
  isLoading = false,
  onNewProject,
  onOpenProject,
  onRefresh,
  onDeleteProject,
  onEditProject,
}: ProjectsTableProps): React.JSX.Element {
  const intl = useIntl();
  /** Column definitions for Carbon `DataTable`. The `actions` column has no header text. */
  const tableHeaders = [
    { key: 'name',         header: intl.formatMessage(messages.headerName)         },
    { key: 'flows',        header: intl.formatMessage(messages.headerFlows)        },
    { key: 'tags',         header: intl.formatMessage(messages.headerTag)          },
    { key: 'lastModified', header: intl.formatMessage(messages.headerLastModified), isSortable: true },
    { key: 'createdOn',    header: intl.formatMessage(messages.headerCreatedOn),    isSortable: true },
    { key: 'actions',      header: ''                                              },
  ];
  const [deleteTarget, setDeleteTarget] = useState<ProjectRow | null>(null);
  const [editTarget, setEditTarget] = useState<ProjectRow | null>(null);

  /** O(1) lookup map from project `id` → `ProjectRow`. Rebuilt only when `rows` changes. */
  const rowMap = useMemo(() => new Map(rows.map((r) => [r.id, r])), [rows]);

  const tableRows = useMemo(
    () => rows.map((r) => ({
      id: r.id,
      name: r.name,
      flows: r.flows,
      // Join tags into a space-separated string so SharedDataTable's built-in
      // search (which only matches string values) can filter by tag text.
      // renderCell below still receives the original tags array via rowMap.
      tags: r.tags.join(' '),
      lastModified: r.lastModified,
      createdOn: r.createdOn,
    })),
    [rows]
  );

  /** Opens the delete modal for the given row. */
  const handleDeleteClick = (row: ProjectRow): void => {
    setDeleteTarget(row);
  };

  /**
   * Forwards the delete call to the parent and closes the modal only on success.
   * Returns a Promise so {@link DeleteModal} can track the in-flight state.
   */
  const handleDeleteConfirm = (): Promise<void> => {
    if (!deleteTarget) { return Promise.resolve(); }
    return onDeleteProject(deleteTarget.id).then(() => {
      setDeleteTarget(null);
    });
  };

  /** Closes the delete modal without taking action. */
  const handleDeleteCancel = (): void => {
    setDeleteTarget(null);
  };

  return (
    <div className={styles.tableWrapper}>
      <SharedDataTable
        headers={tableHeaders}
        rows={tableRows}
        searchable
        searchPlaceholder={intl.formatMessage(messages.searchPlaceholder)}
        paginated={false}
        loading={isLoading}
        size="lg"
        sortRow={(_cellA, _cellB, { key, sortDirection, rowIds: [idA, idB] }) => {
          const rowA = rowMap.get(idA);
          const rowB = rowMap.get(idB);
          if (!rowA || !rowB) { return 0; }
          const dateStrA = key === 'lastModified' ? (rowA.lastModifiedRaw ?? rowA.lastModified) : (rowA.createdOnRaw ?? rowA.createdOn);
          const dateStrB = key === 'lastModified' ? (rowB.lastModifiedRaw ?? rowB.lastModified) : (rowB.createdOnRaw ?? rowB.createdOn);
          const timeA = new Date(dateStrA).getTime();
          const timeB = new Date(dateStrB).getTime();
          return sortDirection === 'ASC' ? timeA - timeB : timeB - timeA;
        }}
        renderToolbarActions={() => (
          <>
            <Button
              kind="ghost"
              size="lg"
              renderIcon={Renew}
              iconDescription={intl.formatMessage(messages.refreshDescription)}
              hasIconOnly
              onClick={onRefresh}
              className={styles.refreshButton}
              tooltipPosition="bottom"
            />
            <Button
              kind="primary"
              size="lg"
              renderIcon={Add}
              onClick={onNewProject}
              className={styles.newProjectButton}
            >
              {intl.formatMessage(messages.newProject)}
            </Button>
          </>
        )}
        renderCell={(cell, row) => {
          const original = rowMap.get(row.id);
          if (!original) { return undefined; }
          switch (cell.info.header) {
            case 'name':
              return (
                <button
                  type="button"
                  className={styles.nameLink}
                  onClick={() => { onOpenProject(row.id); }}
                >
                  {original.name}
                </button>
              );
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
                    itemText={intl.formatMessage(messages.actionEditProject)}
                    onClick={() => { setEditTarget(original); }}
                  />
                  <OverflowMenuItem
                    itemText={intl.formatMessage(messages.actionViewProject)}
                    onClick={() => { onOpenProject(row.id); }}
                  />
                  <OverflowMenuItem
                    itemText={intl.formatMessage(messages.actionDelete)}
                    isDelete
                    hasDivider
                    onClick={() => { handleDeleteClick(original); }}
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
        title={intl.formatMessage(messages.editProjectTitle)}
        initialValues={{
          name: editTarget?.name ?? '',
          description: editTarget?.description ?? '',
          tags: editTarget?.tags ?? [],
        }}
        onCancel={() => { setEditTarget(null); }}
        onEdit={(updates) =>
          onEditProject(editTarget?.id ?? '', updates).then(() => {
            setEditTarget(null);
          })
        }
      />

      <DeleteModal
        open={deleteTarget !== null}
        assetType="Project"
        assetName={deleteTarget?.name ?? ''}
        onCancel={handleDeleteCancel}
        onDelete={handleDeleteConfirm}
      />
    </div>
  );
}
