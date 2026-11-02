/**
 * Output Features Tab — shown in the Properties Panel "Output" tab.
 *
 * Displays features produced by this node grouped by source node.
 * Unchecking "Downstream use" adds the feature to the node's output_features_to_drop
 * parameter, which the backend reads at runtime to drop that column before passing
 * data to downstream nodes. Mandatory features cannot be unchecked.
 * The expand (↗) button opens a Tearsheet (ibm-products) with a Description column added.
 * Both views share the same featureSelections state — checkboxes are always in sync.
 */

import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Button, Checkbox, DefinitionTooltip } from '@carbon/react';
import { Maximize } from '@carbon/icons-react';
import { useIntl } from 'react-intl';
import { NoDataEmptyState } from '@carbon/ibm-products';
import { SharedDataTable } from '@/components/common/SharedDataTable';
import type { SharedDataTableHeader, SharedDataTableRow } from '@/components/common/SharedDataTable';
import { SharedTearsheet } from '@/components/common/SharedTearsheet';
import type { FeatureAttributes } from '@/types';
import styles from './FeaturesTab.module.scss';
import { messages } from './OutputFeaturesTab.messages';

interface OutputFeaturesTabProps {
  nodeId: string;
  outputFeatures: Record<string, FeatureAttributes>;
  pipelineNodes: Array<{ id: string; app_data?: { ui_data?: { label?: string } } }>;
  isLoading: boolean;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  controller: any;
}

export function OutputFeaturesTab({
  nodeId,
  outputFeatures,
  pipelineNodes,
  isLoading,
  controller,
}: OutputFeaturesTabProps): React.JSX.Element {
  const intl = useIntl();
  const [featureSelections, setFeatureSelections] = useState<Record<string, boolean>>({});
  const [isExpanded, setIsExpanded] = useState(false);

  // Downstream use column header — shared between panel and tearsheet headers
  const downstreamHeader = useMemo(() => (
    <DefinitionTooltip
      definition={intl.formatMessage(messages.downstreamTooltip)}
      openOnHover
      align="bottom"
    >
      <span className={styles.downstreamColumnLabel}>
        {intl.formatMessage(messages.downstreamUse)}
      </span>
    </DefinitionTooltip>
  ), [intl]);

  const emptyState = useMemo(() => (
    <NoDataEmptyState
      title={intl.formatMessage(messages.emptyTitle)}
      subtitle={intl.formatMessage(messages.emptySubtitle)}
      size="sm"
    />
  ), [intl]);

  // Compact panel headers (no Description)
  const panelHeaders = useMemo((): SharedDataTableHeader[] => [
    { key: 'name', header: intl.formatMessage(messages.outputFeature) },
    { key: 'columnName', header: intl.formatMessage(messages.columnName) },
    { key: 'type', header: intl.formatMessage(messages.type) },
    { key: 'downstreamUse', header: downstreamHeader },
  ], [intl, downstreamHeader]);

  // Expanded tearsheet headers — adds Description
  const expandedHeaders = useMemo((): SharedDataTableHeader[] => [
    { key: 'name', header: intl.formatMessage(messages.outputFeature) },
    { key: 'columnName', header: intl.formatMessage(messages.columnName) },
    { key: 'description', header: intl.formatMessage(messages.description) },
    { key: 'type', header: intl.formatMessage(messages.type) },
    { key: 'downstreamUse', header: downstreamHeader },
  ], [intl, downstreamHeader]);

  // Seed featureSelections from persisted output_features_to_drop whenever
  // the feature list or the selected node changes.
  useEffect(() => {
    const featureList = Object.values(outputFeatures);
    if (!featureList.length) { return; }
    // eslint-disable-next-line @typescript-eslint/no-unsafe-call, @typescript-eslint/no-unsafe-member-access
    const dropped: string[] = (controller?.getPropertyValue?.({ name: 'output_features_to_drop' }) as string[] | undefined) ?? [];
    const selections: Record<string, boolean> = {};
    for (const f of featureList) {
      selections[f.name] = !dropped.includes(f.name);
    }
    setFeatureSelections(selections);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [outputFeatures, nodeId]);

  const nodeLabels = useMemo(() => {
    const map: Record<string, string> = {};
    for (const n of pipelineNodes) {
      map[n.id] = n.app_data?.ui_data?.label ?? n.id;
    }
    return map;
  }, [pipelineNodes]);

  const toggleFeature = useCallback((featureName: string): void => {
    setFeatureSelections((prev) => {
      const next = { ...prev, [featureName]: !(prev[featureName] ?? true) };
      const dropList = Object.keys(next).filter((key) => !next[key]);
      // eslint-disable-next-line @typescript-eslint/no-unsafe-call, @typescript-eslint/no-unsafe-member-access
      controller?.updatePropertyValue?.({ name: 'output_features_to_drop' }, dropList);
      return next;
    });
  }, [controller]);

  const rows = useMemo((): SharedDataTableRow[] => {
    const featureList = Object.values(outputFeatures);
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
      // _nodeName on every row (header + feature) enables a simple OR search in
      // SharedDataTable via searchKeys: ['name', '_nodeName'] — filtering by either
      // node label or feature name with a single OR match.
      result.push({
        id: `header-${groupIdx}`,
        name: label,
        columnName: '-',
        description: '-',
        type: '-',
        _isGroupHeader: true,
        _featureName: '',
        _isMandatory: false,
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
          _featureName: f.name,
          _isMandatory: f.tags?.includes('mandatory') ?? false,
          _nodeName: label,
        });
      }
      groupIdx++;
    }
    return result;
  }, [outputFeatures, nodeLabels, nodeId]);

  // Stable renderCell for the compact panel — idPrefix 'panel' keeps checkbox IDs unique
  const renderCellPanel = useCallback((
    cell: { id: string; value: React.ReactNode; info: { header: string } },
    row: SharedDataTableRow
  ): React.ReactNode => {
    if (row._isGroupHeader) {
      if (cell.info.header === 'name') {
        return <span className={styles.groupHeaderLabel}>{String(row.name)}</span>;
      }
      return '-';
    }
    if (cell.info.header === 'downstreamUse') {
      const featureName = String(row._featureName ?? '');
      if (!featureName) { return null; }
      const isMandatory = Boolean(row._isMandatory);
      return (
        <Checkbox
          id={`downstream-panel-${row.id}`}
          labelText={intl.formatMessage(messages.enableDownstreamUse, { name: featureName })}
          hideLabel
          checked={isMandatory || (featureSelections[featureName] ?? true)}
          disabled={isMandatory}
          onChange={() => { if (!isMandatory) { toggleFeature(featureName); } }}
        />
      );
    }
    return undefined;
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [featureSelections, outputFeatures, intl]);

  // Stable renderCell for the expanded tearsheet — idPrefix 'modal' keeps checkbox IDs unique
  const renderCellTearsheet = useCallback((
    cell: { id: string; value: React.ReactNode; info: { header: string } },
    row: SharedDataTableRow
  ): React.ReactNode => {
    if (row._isGroupHeader) {
      if (cell.info.header === 'name') {
        return <span className={styles.groupHeaderLabel}>{String(row.name)}</span>;
      }
      return '-';
    }
    if (cell.info.header === 'downstreamUse') {
      const featureName = String(row._featureName ?? '');
      if (!featureName) { return null; }
      const isMandatory = Boolean(row._isMandatory);
      return (
        <Checkbox
          id={`downstream-tearsheet-${row.id}`}
          labelText={intl.formatMessage(messages.enableDownstreamUse, { name: featureName })}
          hideLabel
          checked={isMandatory || (featureSelections[featureName] ?? true)}
          disabled={isMandatory}
          onChange={() => { if (!isMandatory) { toggleFeature(featureName); } }}
        />
      );
    }
    return undefined;
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [featureSelections, outputFeatures, intl]);

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
        renderCell={renderCellPanel}
        renderToolbarActions={() => (
          <Button
            kind="ghost"
            size="md"
            renderIcon={Maximize}
            iconDescription={intl.formatMessage(messages.expandTable)}
            hasIconOnly
            data-testid="expand-output-table"
            onClick={() => { setIsExpanded(true); }}
            className={styles.expandButton}
          />
        )}
      />

      <SharedTearsheet
        open={isExpanded}
        onClose={() => { setIsExpanded(false); }}
        title={intl.formatMessage(messages.tearsheetTitle)}
        primaryActionLabel={intl.formatMessage(messages.save)}
        onPrimaryAction={() => { setIsExpanded(false); }}
        secondaryActionLabel={intl.formatMessage(messages.cancel)}
        onSecondaryAction={() => { setIsExpanded(false); }}
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
            renderCell={renderCellTearsheet}
          />
        </div>
      </SharedTearsheet>
    </div>
  );
}
