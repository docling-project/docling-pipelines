/**
 * @file Feature mapping table for the VectorDB operator tearsheet.
 *
 * Renders a filterable, editable Carbon DataTable of feature-to-column mappings.
 *
 * - Mandatory rows show a disabled checkbox and a warning icon; they cannot be removed.
 * - Non-mandatory rows support batch selection and removal via the toolbar batch action.
 * - Carbon DataTable manages selection state internally via `getBatchActionProps` /
 *   `getSelectionProps` — no manual `selected` flag is tracked per row.
 * - Inline `TextInput` per row allows the user to edit the target column name.
 * - Persistent `TableToolbarSearch` filters visible rows by feature name, description, or column.
 */

import React, { useMemo, useState } from 'react';
import {
  Button,
  DataTable,
  Table,
  TableBody,
  TableBatchAction,
  TableBatchActions,
  TableCell,
  TableContainer,
  TableHead,
  TableHeader,
  TableRow,
  TableSelectRow,
  TableToolbar,
  TableToolbarContent,
  TableToolbarSearch,
  TextInput,
} from '@carbon/react';
import { TrashCan, WarningFilled } from '@carbon/icons-react';
import type { FeatureMappingItem } from '@/types';
import { VECTORDB_LABELS as LABEL } from '../constants';
import styles from './VectorDBFeatureMappingTable.module.scss';

interface VectorDBFeatureMappingTableProps {
  rows: FeatureMappingItem[];
  onColumnChange: (featureName: string, column: string) => void;
  onRemoveSelected: (featureNames: string[]) => void;
  /** Called when user clicks "Add feature mappings" toolbar button */
  onAddClick: () => void;
}

export function VectorDBFeatureMappingTable({
  rows,
  onColumnChange,
  onRemoveSelected,
  onAddClick,
}: VectorDBFeatureMappingTableProps): React.JSX.Element {
  const [searchFilter, setSearchFilter] = useState<string>('');

  const filteredRows = useMemo(() => {
    if (!searchFilter.trim()) { return rows; }
    const q = searchFilter.toLowerCase();
    return rows.filter(
      (r) =>
        r.feature.toLowerCase().includes(q) ||
        r.description.toLowerCase().includes(q) ||
        r.column.toLowerCase().includes(q)
    );
  }, [rows, searchFilter]);

  // Carbon DataTable expects rows with an `id` field — memoized to avoid
  // re-creating the array on every render when filteredRows has not changed.
  const tableRows = useMemo(() => filteredRows.map((r) => ({
    id: r.feature,
    feature: r.feature,
    featureDesc: r.description,
    column: r.column,
    isMandatory: r.isMandatory,
  })), [filteredRows]);

  const headers = [
    { key: 'feature',     header: 'Feature' },
    { key: 'featureDesc', header: 'Feature description' },
    { key: 'column',      header: 'Column' },
    { key: 'required',    header: '' },
  ];

  return (
    <div className={styles.tableContainer}>
      <DataTable rows={tableRows} headers={headers}>
        {({
          rows: carbonRows,
          headers: carbonHeaders,
          getTableProps,
          getHeaderProps,
          getRowProps,
          getSelectionProps,
          getBatchActionProps,
          getToolbarProps,
          getTableContainerProps,
        }) => {
          const selectedRows = carbonRows.filter((r) => r.isSelected && !tableRows.find((t) => t.id === r.id)?.isMandatory);

          return (
            <TableContainer {...getTableContainerProps()}>
              <TableToolbar {...getToolbarProps()} aria-label="Feature mappings table toolbar">
                <TableBatchActions {...getBatchActionProps()}>
                  <TableBatchAction
                    renderIcon={TrashCan}
                    onClick={() => {
                      onRemoveSelected(selectedRows.map((r) => r.id));
                    }}
                  >
                    Remove
                  </TableBatchAction>
                </TableBatchActions>
                <TableToolbarContent>
                  <TableToolbarSearch
                    persistent
                    placeholder="Filter table"
                    value={searchFilter}
                    onChange={(_e: unknown, value?: string) => {
                      setSearchFilter(value ?? '');
                    }}
                  />
                  <Button
                    size="md"
                    kind="primary"
                    className={styles.actionButton}
                    onClick={onAddClick}
                  >
                    {LABEL.ADD_FEATURE_MAPPINGS}
                  </Button>
                </TableToolbarContent>
              </TableToolbar>

              <Table {...getTableProps()} size="md">
                <TableHead>
                  <TableRow>
                    {/* Blank header for the selection column */}
                    <th scope="col" />
                    {carbonHeaders.map((header) => (
                      <TableHeader
                        {...getHeaderProps({ header })}
                        className={header.key === 'required' ? styles.colActions : undefined}
                      >
                        {header.header}
                      </TableHeader>
                    ))}
                  </TableRow>
                </TableHead>
                <TableBody>
                  {carbonRows.map((row) => {
                    const isMandatory = tableRows.find((t) => t.id === row.id)?.isMandatory ?? false;
                    const columnValue = tableRows.find((t) => t.id === row.id)?.column ?? '';

                    return (
                      <TableRow {...getRowProps({ row })}>
                        {/* Mandatory rows get a disabled checkbox so the column aligns
                            with non-mandatory rows and the locked state is visible. */}
                        <TableSelectRow
                          {...getSelectionProps({ row })}
                          disabled={isMandatory}
                          aria-label={`Select feature ${row.id}`}
                        />

                        {row.cells.map((cell) => {
                          if (cell.info.header === 'column') {
                            return (
                              <TableCell key={cell.id}>
                                <TextInput
                                  id={`col-input-${row.id}`}
                                  labelText=""
                                  hideLabel
                                  size="md"
                                  value={columnValue}
                                  className={styles.columnInput}
                                  onChange={(e: React.ChangeEvent<HTMLInputElement>) => {
                                    onColumnChange(row.id, e.target.value);
                                  }}
                                />
                              </TableCell>
                            );
                          }
                          if (cell.info.header === 'required') {
                            return (
                              <TableCell key={cell.id} className={styles.colActions}>
                                {isMandatory && (
                                  <span
                                    className={styles.mandatoryIcon}
                                    title="Required feature — cannot be removed"
                                  >
                                    <WarningFilled size={16} />
                                  </span>
                                )}
                              </TableCell>
                            );
                          }
                          return <TableCell key={cell.id}>{cell.value}</TableCell>;
                        })}
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            </TableContainer>
          );
        }}
      </DataTable>
    </div>
  );
}
