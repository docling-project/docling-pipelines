import React, { useEffect, useMemo, useState } from 'react';
import {
  DataTable,
  DataTableSkeleton,
  Pagination,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableHeader,
  TableRow,
  TableToolbar,
  TableToolbarContent,
  TableToolbarSearch,
} from '@carbon/react';
import { NotFoundEmptyState } from '@carbon/ibm-products';
import { useIntl } from 'react-intl';
import { messages } from './SharedDataTable.messages';
import styles from './SharedDataTable.module.scss';
import {
  DEFAULT_TABLE_PAGE_SIZE,
  DEFAULT_TABLE_PAGE_SIZES,
} from '@/constants/flowRunHistory';

/** A single column definition passed to {@link SharedDataTable}. */
export interface SharedDataTableHeader {
  /** Matches the key in each {@link SharedDataTableRow} object. */
  key: string;
  /** Column heading content (string or React node). */
  header: React.ReactNode;
  /** Whether this column header is sortable. */
  isSortable?: boolean;
}

/** A single data row passed to {@link SharedDataTable}. Must include a unique `id`. */
export interface SharedDataTableRow {
  /** Unique row identifier used by Carbon DataTable for keying and state tracking. */
  id: string;
  /** Dynamic cell values keyed by column key. Values may be any React-renderable type. */
  [key: string]: React.ReactNode;
}

/**
 * Props for {@link SharedDataTable}.
 */
interface SharedDataTableProps {
  /** Column definitions — order determines left-to-right display order. */
  headers: SharedDataTableHeader[];
  /** Row data. Each row must have an `id` plus one key per header. */
  rows: SharedDataTableRow[];
  /** Optional table title rendered above the toolbar (passed to Carbon `TableContainer`). */
  title?: string;
  /** Optional table description rendered below the title. */
  description?: string;
  /** Available page-size options shown in the pagination control. */
  pageSizes?: number[];
  /** Initial page size selected when the table first renders. */
  initialPageSize?: number;
  /** When `true`, adds a toolbar with a search input. Filtering is handled internally. */
  searchable?: boolean;
  /**
   * Row keys to search against. When provided, only these string fields are tested.
   * When omitted, all string-valued fields are tested (legacy behaviour).
   */
  searchKeys?: string[];
  /** Placeholder text for the toolbar search input. */
  searchPlaceholder?: string;
  /**
   * Optional content rendered at the left end of the toolbar (e.g. a status filter
   * dropdown), before the search input. Forces the toolbar to render even when
   * `searchable` is `false`.
   */
  renderToolbarLeft?: () => React.ReactNode;
  /**
   * When `false`, renders all `rows` without slicing or a `Pagination` control.
   * Defaults to `true`. Set to `false` for tables that are expected to show their
   * full row set inline (e.g. within a page that already has its own layout).
   */
  paginated?: boolean;
  /** When `true`, hides the table and shows a `DataTableSkeleton` instead. */
  loading?: boolean;
  /** Content rendered when `rows` is empty and `loading` is `false`. */
  emptyState?: React.ReactNode;
  /**
   * Custom cell renderer. Called for every non-header cell.
   * Return `undefined` to fall back to the default `cell.value` rendering.
   */
  renderCell?: (cell: { id: string; value: React.ReactNode; info: { header: string } }, row: SharedDataTableRow) => React.ReactNode;
  /**
   * Optional extra content rendered immediately after each data row inside the same
   * `<tbody>`. Return `null` to render nothing for a given row. Use this to inject
   * expand/detail rows that must appear inline between data rows.
   */
  renderRowExtras?: (row: SharedDataTableRow) => React.ReactNode;
  /** Size variant forwarded to the Carbon `Table` component. */
  size?: 'xs' | 'sm' | 'md' | 'lg' | 'xl';
  /**
   * Optional extra actions (e.g. icon buttons) rendered at the right end of the toolbar.
   * Only shown when `searchable` is `true` — the toolbar must be present.
   */
  renderToolbarActions?: () => React.ReactNode;
  /**
   * When `true`, wraps the `<Table>` in a horizontally-scrollable container and
   * sets `min-width: max-content` on the table so columns expand to their natural
   * widths. Use for tables with many columns in constrained-width containers
   * (e.g. properties panel flyout).
   * Defaults to `false` to preserve existing layout for all other callers.
   */
  horizontalScroll?: boolean;
  /** Whether sorting is enabled for the entire table or individual columns. */
  isSortable?: boolean;
  /** Custom comparator callback passed to Carbon DataTable `sortRow`. */
  sortRow?: (
    cellA: unknown,
    cellB: unknown,
    params: {
      key: string;
      sortDirection: 'ASC' | 'DESC' | 'NONE';
      sortStates: { ASC: 'ASC'; DESC: 'DESC'; NONE: 'NONE' };
      locale: string;
      compare: (a: unknown, b: unknown, locale?: string) => number;
      rowIds: [string, string];
    }
  ) => number;
}

/** Conditionally wraps children in a scroll div. Renders children bare when `active` is false. */
function MaybeScrollWrapper({
  active, className, children,
}: Readonly<{ active: boolean; className: string | undefined; children: React.ReactNode }>): React.JSX.Element {
  return active ? <div className={className}>{children}</div> : <>{children}</>;
}

/**
 * Reusable data table with built-in pagination, optional toolbar search, and a
 * skeleton loading state.
 *
 * Features:
 * - Client-side search filtering (opt-in via `searchable`).
 * - Pagination with configurable page sizes; page resets automatically on search or row-count change.
 *   Can be disabled entirely via `paginated={false}`.
 * - `emptyState` slot rendered instead of the table when rows is empty and not loading.
 * - `renderCell` escape hatch for custom cell content (e.g. tags, links, overflow menus).
 * - `renderToolbarActions` slot for additional toolbar buttons (right side).
 * - `renderToolbarLeft` slot for additional toolbar content (left side, e.g. a status filter).
 */
export function SharedDataTable({
  headers,
  rows,
  title,
  description,
  pageSizes = [...DEFAULT_TABLE_PAGE_SIZES],
  initialPageSize = DEFAULT_TABLE_PAGE_SIZE,
  searchable = false,
  searchPlaceholder,
  renderToolbarLeft,
  paginated = true,
  loading = false,
  emptyState,
  renderCell,
  renderRowExtras,
  size = 'md',
  renderToolbarActions,
  searchKeys,
  horizontalScroll = false,
  isSortable,
  sortRow,
}: SharedDataTableProps): React.JSX.Element {
  const intl = useIntl();
  const resolvedSearchPlaceholder = searchPlaceholder ?? intl.formatMessage(messages.searchPlaceholder);

  const normalizedInitialPageSize = pageSizes.includes(initialPageSize)
    ? initialPageSize
    : pageSizes[0] ?? DEFAULT_TABLE_PAGE_SIZE;

  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState<number>(normalizedInitialPageSize);
  const [searchValue, setSearchValue] = useState('');

  // Reset to page 1 whenever the search term or row set changes
  useEffect(() => {
    setPage(1);
  }, [searchValue, rows.length]);

  useEffect(() => {
    const totalPages = Math.max(1, Math.ceil(rows.length / pageSize));
    if (page > totalPages) {
      setPage(totalPages);
    }
  }, [page, pageSize, rows.length]);

  const filteredRows = useMemo(() => {
    if (!searchable || !searchValue) { return rows; }
    const q = searchValue.toLowerCase();
    return rows.filter((row) => {
      const keys = searchKeys ?? Object.keys(row);
      return keys.some((k) => {
        const v = row[k];
        return typeof v === 'string' && v.toLowerCase().includes(q);
      });
    });
  }, [rows, searchValue, searchable, searchKeys]);

  // Build a lookup from row id → original row for renderCell access
  const rowById = useMemo(() => {
    const map: Record<string, SharedDataTableRow> = {};
    for (const row of filteredRows) {
      map[row.id] = row;
    }
    return map;
  }, [filteredRows]);

  if (loading) {
    return (
      <DataTableSkeleton
        columnCount={headers.length}
        rowCount={5}
        size={size}
        showHeader={false}
        showToolbar={searchable || Boolean(renderToolbarLeft)}
      />
    );
  }

  return (
    /* eslint-disable react/jsx-props-no-spreading */
    <DataTable
      rows={filteredRows}
      headers={headers}
      isSortable={isSortable}
      sortRow={sortRow}
    >
      {({
        rows: tableRows,
        headers: tableHeaders,
        getTableProps,
        getHeaderProps,
        getRowProps,
      }) => {
        const visibleRows = paginated
          ? tableRows.slice((page - 1) * pageSize, (page - 1) * pageSize + pageSize)
          : tableRows;

        let tableContent: React.ReactNode;
        if (filteredRows.length === 0 && searchValue) {
          // Search produced zero results — keep the toolbar mounted so the user
          // can clear the query, show a centred NotFoundEmptyState below it.
          tableContent = (
            <div className={styles.emptyStateWrapper}>
              <NotFoundEmptyState
                title={intl.formatMessage(messages.noResultsTitle)}
                subtitle={intl.formatMessage(messages.noResultsSubtitle, { searchValue })}
                size="sm"
              />
            </div>
          );
        } else if (filteredRows.length === 0 && emptyState) {
          // No data at all — show the caller-supplied empty state, centred.
          tableContent = <div className={styles.emptyStateWrapper}>{emptyState}</div>;
        } else {
          tableContent = (
            <>
              <MaybeScrollWrapper active={horizontalScroll} className={styles.tableScrollX}>
                <Table {...getTableProps()} size={size} className={horizontalScroll ? styles.scrollableTable : undefined}>
                  <TableHead>
                    <TableRow>
                      {tableHeaders.map((header) => (
                        <TableHeader
                          {...getHeaderProps({
                            header,
                            isSortable: header.isSortable ?? isSortable,
                          })}
                          key={header.key}
                        >
                          {header.header}
                        </TableHeader>
                      ))}
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {visibleRows.map((row) => {
                      const originalRow = rowById[row.id] ?? { id: row.id };
                      return (
                        <React.Fragment key={row.id}>
                          <TableRow {...getRowProps({ row })}>
                            {row.cells.map((cell) => {
                              const custom = renderCell
                                ? renderCell(cell as { id: string; value: React.ReactNode; info: { header: string } }, originalRow)
                                : undefined;
                              return (
                                <TableCell key={cell.id}>
                                  {custom !== undefined ? custom : cell.value}
                                </TableCell>
                              );
                            })}
                          </TableRow>
                          {renderRowExtras ? renderRowExtras(originalRow) : null}
                        </React.Fragment>
                      );
                    })}
                  </TableBody>
                </Table>
              </MaybeScrollWrapper>
              {paginated && (
                <Pagination
                  page={page}
                  pageSize={pageSize}
                  pageSizes={pageSizes}
                  totalItems={filteredRows.length}
                  onChange={({ page: p, pageSize: ps }) => {
                    setPage(p);
                    setPageSize(ps);
                  }}
                />
              )}
            </>
          );
        }

        return (
          <TableContainer title={title} description={description}>
            {(searchable || renderToolbarLeft) && (
              <TableToolbar>
                {renderToolbarLeft?.()}
                <TableToolbarContent>
                  {searchable && (
                    <TableToolbarSearch
                      placeholder={resolvedSearchPlaceholder}
                      onChange={(_e, value) => { setSearchValue(value ?? ''); }}
                      persistent
                    />
                  )}
                  {renderToolbarActions?.()}
                </TableToolbarContent>
              </TableToolbar>
            )}
            {tableContent}
          </TableContainer>
        );
      }}
    </DataTable>
    /* eslint-enable react/jsx-props-no-spreading */
  );
}
