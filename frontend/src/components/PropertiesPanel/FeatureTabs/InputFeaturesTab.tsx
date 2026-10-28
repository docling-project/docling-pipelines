/**
 * Input Features Tab — shown in the Properties Panel "Input" tab.
 *
 * Displays features flowing into the selected node from upstream operators,
 * grouped by the source node that introduced them.
 * The expand (↗) button opens a Tearsheet (ibm-products) with a Description column added.
 */

import React, { useMemo, useState } from 'react';
import { Button } from '@carbon/react';
import { NoDataEmptyState, Tearsheet } from '@carbon/ibm-products';
import { Maximize } from '@carbon/icons-react';
import { useIntl } from 'react-intl';
import { SharedDataTable } from '@/components/common/SharedDataTable';
import type { SharedDataTableHeader, SharedDataTableRow } from '@/components/common/SharedDataTable';
import type { FeatureAttributes } from '@/types';
import styles from './FeaturesTab.module.scss';
import { messages } from './InputFeaturesTab.messages';

interface InputFeaturesTabProps {
  nodeId: string;
  inputFeatures: Record<string, FeatureAttributes>;
  pipelineNodes: Array<{ id: string; app_data?: { ui_data?: { label?: string } } }>;
  isLoading: boolean;
}

export function InputFeaturesTab({
  nodeId,
  inputFeatures,
  pipelineNodes,
  isLoading,
}: InputFeaturesTabProps): React.JSX.Element {
  const intl = useIntl();
  const [isExpanded, setIsExpanded] = useState(false);

  // Compact panel headers (no Description column — not enough width)
  const panelHeaders = useMemo((): SharedDataTableHeader[] => [
    { key: 'name', header: intl.formatMessage(messages.inputFeature) },
    { key: 'columnName', header: intl.formatMessage(messages.columnName) },
    { key: 'type', header: intl.formatMessage(messages.type) },
  ], [intl]);

  // Expanded tearsheet headers — adds Description
  const expandedHeaders = useMemo((): SharedDataTableHeader[] => [
    { key: 'name', header: intl.formatMessage(messages.inputFeature) },
    { key: 'columnName', header: intl.formatMessage(messages.columnName) },
    { key: 'description', header: intl.formatMessage(messages.description) },
    { key: 'type', header: intl.formatMessage(messages.type) },
  ], [intl]);

  const emptyState = useMemo(() => (
    <NoDataEmptyState
      title={intl.formatMessage(messages.emptyTitle)}
      subtitle={intl.formatMessage(messages.emptySubtitle)}
      size="sm"
    />
  ), [intl]);

  const nodeLabels = useMemo(() => {
    const map: Record<string, string> = {};
    for (const n of pipelineNodes) {
      map[n.id] = n.app_data?.ui_data?.label ?? n.id;
    }
    return map;
  }, [pipelineNodes]);

  const rows = useMemo((): SharedDataTableRow[] => {
    const featureList = Object.values(inputFeatures);
    if (!featureList.length) { return []; }

    const groups: Record<string, FeatureAttributes[]> = {};
    for (const feature of featureList) {
      const srcId = feature.node_id ?? 'unknown';
      groups[srcId] ??= [];
      groups[srcId].push(feature);
    }

    // Current node's group first, remaining in natural order
    const sortedNodeIds = Object.keys(groups).sort((a, b) =>
      a === nodeId ? -1 : b === nodeId ? 1 : 0
    );

    const result: SharedDataTableRow[] = [];
    let groupIdx = 0;
    for (const nId of sortedNodeIds) {
      const features = groups[nId];
      const label = nodeLabels[nId] ?? nId;
      // Group header row
      result.push({
        id: `header-${groupIdx}`,
        name: label,
        columnName: '-',
        description: '-',
        type: '',
        _isGroupHeader: true,
        _nodeName: label,
      });
      for (const f of features) {
        result.push({
          id: `feature-${groupIdx}-${f.name}`,
          name: f.name,
          columnName: f.name,
          description: f.description ?? '',
          type: f.type,
          _isGroupHeader: false,
          _nodeName: label,
        });
      }
      groupIdx++;
    }
    return result;
  }, [inputFeatures, nodeLabels, nodeId]);

  const renderCellFn = (
    cell: { id: string; value: React.ReactNode; info: { header: string } },
    row: SharedDataTableRow
  ): React.ReactNode => {
    if (row._isGroupHeader) {
      if (cell.info.header === 'name') {
        return <span className={styles.groupHeaderLabel}>{String(row.name)}</span>;
      }
      return '-';
    }
    return undefined; // default rendering
  };

  return (
    <div className={styles.featuresTab}>
      <p className={styles.tabDescription}>
        {intl.formatMessage(messages.tabDescription)}
      </p>
      <SharedDataTable
        headers={panelHeaders}
        rows={rows}
        searchable
        searchKeys={['name', '_nodeName']}
        searchPlaceholder={intl.formatMessage(messages.searchPlaceholder)}
        loading={isLoading}
        emptyState={emptyState}
        size="lg"
        horizontalScroll
        renderCell={renderCellFn}
        renderToolbarActions={() => (
          <Button
            kind="ghost"
            size="md"
            renderIcon={Maximize}
            iconDescription={intl.formatMessage(messages.expandTable)}
            hasIconOnly
            onClick={() => { setIsExpanded(true); }}
            className={styles.expandButton}
          />
        )}
      />

      <Tearsheet
        open={isExpanded}
        onClose={() => { setIsExpanded(false); }}
        title={intl.formatMessage(messages.tearsheetTitle)}
        description={intl.formatMessage(messages.tearsheetDescription)}
        actions={[
          {
            label: intl.formatMessage(messages.close),
            kind: 'secondary' as const,
            onClick: () => { setIsExpanded(false); },
          },
        ]}
        hasCloseIcon
        closeIconDescription={intl.formatMessage(messages.close)}
      >
        <div className={styles.tearsheetTableWrapper}>
          <SharedDataTable
            key={String(isExpanded)}
            headers={expandedHeaders}
            rows={rows}
            searchable
            searchKeys={['name', '_nodeName']}
            searchPlaceholder={intl.formatMessage(messages.searchPlaceholder)}
            loading={isLoading}
            emptyState={emptyState}
            size="lg"
            horizontalScroll
            renderCell={renderCellFn}
          />
        </div>
      </Tearsheet>
    </div>
  );
}
