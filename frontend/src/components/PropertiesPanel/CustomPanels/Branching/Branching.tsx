/**
 * @file Branching.tsx
 *
 * Configuration panel body for the `branching` operator node.
 *
 * Shows a read-only table of each outgoing link's **target node** and
 * **link name**. The link name and condition are set directly on the canvas
 * link via the `LinkConditionTearsheet` (opened from the link's context
 * toolbar / decoration click), so no editing controls live here.
 *
 * Data is derived from `branchingNode.parameters.link_conditions` — the same
 * array that Canvas.tsx populates when the user saves a condition.
 *
 * @module Branching
 */

import React, { useMemo } from 'react';
import { DataTable, TableContainer, Table, TableHead, TableRow, TableHeader, TableBody, TableCell } from '@carbon/react';
import { useIntl } from 'react-intl';
import type { ElyraController } from '@/types';
import styles from './Branching.module.scss';
import { messages } from './Branching.messages';

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface BranchingPanelBodyProps {
  controller: ElyraController;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

/**
 * Configuration panel body for the `branching` operator.
 *
 * Displays a summary table: one row per outgoing link, showing the target
 * node's display label and the link's condition name. Links with no saved
 * condition yet show an em-dash placeholder.
 */
export function BranchingPanelBody({ controller }: BranchingPanelBodyProps): React.JSX.Element {
  const intl = useIntl();
  const appData = controller.getAppData() as {
    nodeId?: string;
    pipelineFlow?: { pipelines?: Array<{ nodes?: Array<Record<string, unknown>> }> };
  };

  const nodeId = appData.nodeId ?? '';
  const {pipelineFlow} = appData;

  /** Derive link-condition rows from the pipeline flow JSON. */
  const rows = useMemo(() => {
    if (!pipelineFlow) { return []; }

    const nodes = (pipelineFlow.pipelines?.[0]?.nodes ?? []);
    const branchingNode = nodes.find((n) => n['id'] === nodeId);
    const params        = branchingNode?.['parameters'] as Record<string, unknown> | undefined;
    const linkConditions = (params?.['link_conditions'] as Array<Record<string, unknown>> | undefined) ?? [];

    return linkConditions
      .filter((lc) => (lc['link_name'] as string | undefined)?.trim()) // only show named links
      .map((lc) => {
        const targetNode = nodes.find((n) => n['id'] === (lc['target_node_id'] as string));
        const targetParams = targetNode?.['parameters'] as Record<string, unknown> | undefined;
        const targetUiData = ((targetNode?.['app_data'] as Record<string, unknown> | undefined)?.['ui_data']) as Record<string, unknown> | undefined;
        const targetLabel: string =
          (targetParams?.['display_label'] as string | undefined) ??
          (targetUiData?.['label']         as string | undefined) ??
          (lc['target_node_id']            as string | undefined) ??
          '—';
        return {
          id:       lc['link_id'] as string,
          nodeName: targetLabel,
          linkName: (lc['link_name'] as string | undefined) ?? '—',
        };
      });
  }, [pipelineFlow, nodeId]);

  const headers = [
    { key: 'nodeName', header: intl.formatMessage(messages.targetNode) },
    { key: 'linkName', header: intl.formatMessage(messages.linkName) },
  ];

  if (rows.length === 0) {
    return (
      <div className={styles.emptyState}>
        <p>{intl.formatMessage(messages.emptyState)}</p>
      </div>
    );
  }

  return (
    <div className={styles.panelBody}>
      <p className={styles.helperText}>
        {intl.formatMessage(messages.helperText)}
      </p>
      <DataTable rows={rows} headers={headers}>
        {({ rows: tableRows, headers: tableHeaders, getTableProps, getHeaderProps, getRowProps }) => (
          <TableContainer>
            {/* eslint-disable-next-line react/jsx-props-no-spreading */}
            <Table {...getTableProps()} size="sm">
              <TableHead>
                <TableRow>
                  {tableHeaders.map((header) => (
                    // eslint-disable-next-line react/jsx-key, react/jsx-props-no-spreading
                    <TableHeader {...getHeaderProps({ header })}>
                      {header.header}
                    </TableHeader>
                  ))}
                </TableRow>
              </TableHead>
              <TableBody>
                {tableRows.map((row) => (
                  // eslint-disable-next-line react/jsx-key, react/jsx-props-no-spreading
                  <TableRow {...getRowProps({ row })}>
                    {row.cells.map((cell) => (
                      <TableCell key={cell.id}>{cell.value}</TableCell>
                    ))}
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TableContainer>
        )}
      </DataTable>
    </div>
  );
}
