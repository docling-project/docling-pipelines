/**
 * @file Feature mapping summary table for the VectorDB properties panel.
 *
 * Displayed in the properties panel after the user saves feature mappings from
 * the tearsheet. Owns its own search filter and row-selection state internally.
 * The parent panel provides the data and handles all persistence via the
 * `onRemove` and `onEdit` callbacks.
 */

import React, { useState } from 'react';
import { useIntl } from 'react-intl';
import {
  Button,
  DataTableSkeleton,
  FormLabel,
  Table,
  TableBatchAction,
  TableBatchActions,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableHeader,
  TableRow,
  TableSelectAll,
  TableSelectRow,
  TableToolbar,
  TableToolbarContent,
  TableToolbarSearch,
} from '@carbon/react';
import { TrashCan } from '@carbon/icons-react';
import { messages } from './VectorDBSummaryTable.messages';
import styles from './VectorDB.module.scss';

export interface SummaryRow {
  feature: string;
  column: string;
  isMandatory: boolean;
}

interface VectorDBSummaryTableProps {
  savedResourceName: string;
  rows: SummaryRow[];
  /** Called with the feature names to remove when the user selects rows and clicks "Remove". */
  onRemove: (featureNames: string[]) => void;
  onEdit: () => void;
  /** When true the enrich API is still in-flight — show a skeleton instead of the table. */
  loading?: boolean;
}

/** Summary table — owns search and row-selection state internally. */
export function VectorDBSummaryTable({
  savedResourceName,
  rows,
  onRemove,
  onEdit,
  loading = false,
}: VectorDBSummaryTableProps): React.JSX.Element {
  const intl = useIntl();
  const [searchFilter, setSearchFilter] = useState('');
  const [selectedRows, setSelectedRows] = useState<Set<string>>(new Set());

  const filteredRows = searchFilter.trim()
    ? rows.filter((r) =>
        r.feature.toLowerCase().includes(searchFilter.toLowerCase()) ||
        r.column.toLowerCase().includes(searchFilter.toLowerCase())
      )
    : rows;

  const selectableRows = rows.filter((r) => !r.isMandatory);
  const selectedRemovable = selectableRows.filter((r) => selectedRows.has(r.feature));
  const allSelected =
    selectableRows.length > 0 && selectableRows.every((r) => selectedRows.has(r.feature));

  const handleRemove = (): void => {
    onRemove([...selectedRows]);
    setSelectedRows(new Set());
  };

  const featureMappingsConfigLabel = intl.formatMessage(messages.featureMappingsConfig);

  if (loading) {
    return (
      <div>
        <FormLabel>{featureMappingsConfigLabel}</FormLabel>
        <DataTableSkeleton
          columnCount={3}
          rowCount={rows.length || 3}
          showHeader={false}
          showToolbar={false}
        />
      </div>
    );
  }

  return (
    <div>
      <FormLabel>{featureMappingsConfigLabel}</FormLabel>
      <div className={styles.resourceTableSection}>
        <h5 className={styles.resourceNameSection}>{savedResourceName}</h5>
        <TableContainer>
          <TableToolbar>
            <TableBatchActions
              shouldShowBatchActions={selectedRemovable.length > 0}
              totalCount={selectedRemovable.length}
              totalSelected={selectedRemovable.length}
              onCancel={() => { setSelectedRows(new Set()); }}
            >
              <TableBatchAction renderIcon={TrashCan} onClick={handleRemove}>
                {intl.formatMessage(messages.remove)}
              </TableBatchAction>
            </TableBatchActions>
            <TableToolbarContent>
              <TableToolbarSearch
                persistent
                placeholder={intl.formatMessage(messages.searchPlaceholder)}
                value={searchFilter}
                onChange={(_e: unknown, value?: string) => { setSearchFilter(value ?? ''); }}
              />
              <Button
                kind="ghost"
                size="sm"
                className={styles.editButton}
                aria-label={intl.formatMessage(messages.editFeatureMappingsAria)}
                onClick={onEdit}
              >
                {intl.formatMessage(messages.editFeatureMappings)}
              </Button>
            </TableToolbarContent>
          </TableToolbar>
          <Table size="md" className={styles.summaryTable}>
            <TableHead>
              <TableRow>
                <TableSelectAll
                  id="summary-select-all"
                  name="summary-select-all"
                  checked={allSelected}
                  indeterminate={!allSelected && selectableRows.some((r) => selectedRows.has(r.feature))}
                  aria-label={intl.formatMessage(messages.selectAllAria)}
                  onSelect={() => {
                    setSelectedRows(allSelected
                      ? new Set()
                      : new Set(selectableRows.map((r) => r.feature))
                    );
                  }}
                />
                <TableHeader>{intl.formatMessage(messages.featureHeader)}</TableHeader>
                <TableHeader>{intl.formatMessage(messages.columnHeader)}</TableHeader>
              </TableRow>
            </TableHead>
            <TableBody>
              {filteredRows.map((row) => (
                <TableRow key={row.feature}>
                  <TableSelectRow
                    id={`summary-select-${row.feature}`}
                    name={`summary-select-${row.feature}`}
                    checked={selectedRows.has(row.feature)}
                    disabled={row.isMandatory}
                    aria-label={intl.formatMessage(messages.selectFeatureAria, { feature: row.feature })}
                    onSelect={() => {
                      if (row.isMandatory) { return; }
                      setSelectedRows((prev) => {
                        const next = new Set(prev);
                        if (next.has(row.feature)) { next.delete(row.feature); } else { next.add(row.feature); }
                        return next;
                      });
                    }}
                  />
                  <TableCell>{row.feature}</TableCell>
                  <TableCell>{row.column}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableContainer>
      </div>
    </div>
  );
}
