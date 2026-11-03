/**
 * @file Merging.tsx
 *
 * Configuration panel body for the `merge` operator node.
 * Includes a preview tearsheet that illustrates each merge mode with sample data:
 *   - Fixed-width table boxes (spacing-13 * 2.7 ≈ 259px)
 *   - Absolute-positioned SVG overlay (x=400, 600, 630→800)
 *   - Stacked circles for row merges, Venn diagram for column joins
 *   - Row colour-coding (branch1=blue-20, branch2=purple-20)
 *   - Per-cell warning icons for null/missing values
 *
 * @module Merging
 */

/* eslint-disable @typescript-eslint/no-explicit-any */

import React, { useState, useMemo, useEffect, useRef } from 'react';
import { useIntl } from 'react-intl';
import {
  RadioButton,
  Dropdown,
  InlineNotification,
  Button,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableHeader,
  TableRow,
} from '@carbon/react';
import { WarningAlt } from '@carbon/icons-react';
import { Tearsheet } from '@carbon/ibm-products';
import type { ElyraController } from '@/types';
import { enrichFlowFeatures } from '@/services/api';
import { messages } from './Merging.messages';
import styles from './Merging.module.scss';

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const MERGE_TYPE = {
  ROWS:    'rows',
  COLUMNS: 'columns',
} as const;

const COLUMN_OPTION = {
  INNER_JOIN: 'inner_join',
  FULL_OUTER: 'full_outer',
} as const;

// Preview mode identifiers
const PREVIEW_TYPE = {
  MERGE_ROWS:  'MergeRowsPreview',
  INNER_JOIN:  'InnerJoinPreview',
  FULL_OUTER:  'FullOuterPreview',
} as const;

type MergeType    = typeof MERGE_TYPE[keyof typeof MERGE_TYPE];
type ColumnOption = typeof COLUMN_OPTION[keyof typeof COLUMN_OPTION];
type PreviewType  = typeof PREVIEW_TYPE[keyof typeof PREVIEW_TYPE];

// ---------------------------------------------------------------------------
// Sample data for preview tearsheet
// ---------------------------------------------------------------------------

const D = {
  row1: '111', row2: '112', row3: '113', row4: '113', row5: '121',
  q1: '0.56',  q2: '0.78',  q3: '0.99',  q4: '1.0',
  doc1: 'doc1', doc2: 'doc2', doc4: 'doc4', doc9: 'doc9',
  alice: 'Alice', bob: 'Bob', charlie: 'Charlie',
  english: 'English', french: 'French', german: 'German',
  Null: 'Null',
};

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

// Cell with optional warning icon
function CellContent({ content, showWarning = false }: { content: string; showWarning?: boolean }): React.JSX.Element {
  if (showWarning) {
    return (
      <>
        <WarningAlt size={16} className={styles.warningIcon} />
        {content}
      </>
    );
  }
  return <>{content}</>;
}

// Table row with per-cell class names and optional warning indexes
function TableRowWithCells({
  rowData,
  rowKey,
  rowClassName = '',
  cellClassNames = [],
  showWarningForIndexes = [],
}: {
  rowData: string[];
  rowKey: string;
  rowClassName?: string;
  cellClassNames?: string[];
  showWarningForIndexes?: number[];
}): React.JSX.Element {
  return (
    <TableRow className={rowClassName}>
      {rowData.map((cell, ci) => (
        <TableCell key={`${rowKey}-${ci}`} className={cellClassNames[ci] ?? ''}>
          <CellContent content={cell} showWarning={showWarningForIndexes.includes(ci)} />
        </TableCell>
      ))}
    </TableRow>
  );
}

// Branch input table
function PreviewTable({
  title,
  headers,
  rows,
  tableType = 'branch1',
  className = '',
}: {
  title: string;
  headers: string[];
  rows: string[][];
  tableType?: 'branch1' | 'branch2';
  className?: string;
}): React.JSX.Element {
  const rowClass = tableType === 'branch2' ? styles.branch2Row : styles.branch1Row;
  const boxClass = tableType === 'branch2' ? styles.branch2Table : styles.branch1Table;
  return (
    <div className={`${styles.tableBox} ${boxClass}`}>
      <h5>{title}</h5>
      <TableContainer>
        <Table size="sm" className={className}>
          <TableHead>
            <TableRow>
              {headers.map((h) => <TableHeader key={h}>{h}</TableHeader>)}
            </TableRow>
          </TableHead>
          <TableBody>
            {rows.map((row, ri) => (
              <TableRowWithCells
                key={`${title}-${ri}`}
                rowData={row}
                rowKey={`${title}-${ri}`}
                rowClassName={rowClass}
              />
            ))}
          </TableBody>
        </Table>
      </TableContainer>
    </div>
  );
}

// Merged output table
function MergedTablePreview({ previewType }: { previewType: PreviewType }): React.JSX.Element {
  const intl = useIntl();
  const headers = previewType === PREVIEW_TYPE.MERGE_ROWS
    ? [
        intl.formatMessage(messages.headerDocId),
        intl.formatMessage(messages.headerName),
        intl.formatMessage(messages.headerAuthor),
        intl.formatMessage(messages.headerLanguage),
        intl.formatMessage(messages.headerQuality),
      ]
    : [
        intl.formatMessage(messages.headerDocId),
        intl.formatMessage(messages.headerName),
        intl.formatMessage(messages.headerAuthor),
        intl.formatMessage(messages.headerLanguage),
        intl.formatMessage(messages.headerNameLinkname),
        intl.formatMessage(messages.headerQuality),
      ];

  // CSS module classes typed as string|undefined — use '' as fallback
  const b2 = styles.branch2Row ?? '';

  type MergedRow = { data: string[]; cellClassNames: string[]; showWarningForIndexes?: number[] };
  let rows: MergedRow[] = [];

  if (previewType === PREVIEW_TYPE.INNER_JOIN) {
    rows = [
      { data: [D.row1, D.doc1, D.alice, D.english, D.doc1, D.q1], cellClassNames: ['','','','',b2,b2] },
      { data: [D.row2, D.doc2, D.bob,   D.german,  D.doc2, D.q2], cellClassNames: ['','','','',b2,b2] },
    ];
  } else if (previewType === PREVIEW_TYPE.MERGE_ROWS) {
    rows = [
      { data: [D.row1, D.doc1, D.alice,   D.english, D.Null], cellClassNames: ['','','','',''] },
      { data: [D.row2, D.doc2, D.bob,     D.german,  D.Null], cellClassNames: ['','','','',''] },
      { data: [D.row4, D.doc4, D.charlie, D.french,  D.Null], cellClassNames: ['','','','',''] },
      {
        data: [D.row5, D.doc9, D.Null, D.english, D.q4],
        cellClassNames: [b2, b2, b2, b2, b2],
        showWarningForIndexes: [2],
      },
    ];
  } else {
    // FULL_OUTER
    rows = [
      { data: [D.row1, D.doc1, D.alice,   D.english, D.doc1, D.q1],   cellClassNames: ['','','','',b2,b2] },
      { data: [D.row2, D.doc2, D.bob,     D.german,  D.doc2, D.q2],   cellClassNames: ['','','','',b2,b2] },
      { data: [D.row4, D.doc4, D.charlie, D.french,  D.Null, D.Null], cellClassNames: ['','','','',b2,b2], showWarningForIndexes: [4,5] },
      { data: [D.row3, D.Null, D.Null,    D.Null,    D.doc4, D.q3],   cellClassNames: ['','','','',b2,b2], showWarningForIndexes: [1,2,3] },
    ];
  }

  return (
    <div className={`${styles.tableBox} ${styles.mergedTable}`}>
      <h5>{intl.formatMessage(messages.mergedTableTitle)}</h5>
      <TableContainer>
        <Table size="sm">
          <TableHead>
            <TableRow>
              {headers.map((h) => <TableHeader key={h}>{h}</TableHeader>)}
            </TableRow>
          </TableHead>
          <TableBody>
            {rows.map((row, ri) => (
              <TableRowWithCells
                key={`merged-${ri}`}
                rowData={row.data}
                rowKey={`merged-${ri}`}
                rowClassName={styles.branch1Row}
                cellClassNames={row.cellClassNames}
                showWarningForIndexes={row.showWarningForIndexes ?? []}
              />
            ))}
          </TableBody>
        </Table>
      </TableContainer>
    </div>
  );
}

// ---------------------------------------------------------------------------
// DiagramSvg — SVG connector overlay for the merge preview diagram.
// Coordinates are calibrated against fixed table widths:
//   tableBox width  ≈ 6rem * 2.7 = 259px  (left tables column)
//   gap             ≈ 2.5rem = 40px        (mergePreviewLayout gap)
//   SVG x=400  → right edge of left column (259 + gap padding)
//   SVG x=600  → connector midpoint
//   SVG x=630→800 → arrow to merged table
// ---------------------------------------------------------------------------

type DiagramSvgProps = { previewType: PreviewType };

function DiagramSvg({ previewType }: DiagramSvgProps): React.JSX.Element {
  const intl = useIntl();

  // Circle fill colours for each preview mode
  const TRANSPARENT = 'transparent';
  const LIGHT_BLUE   = 'var(--merging-blue-light)';
  const LIGHT_PURPLE = 'var(--merging-purple-light)';
  const BLUE         = 'var(--merging-blue)';
  const PURPLE       = 'var(--merging-purple)';
  const GRAY         = 'var(--cds-text-secondary, #525252)';

  let blueCircleFill   = TRANSPARENT;
  let purpleCircleFill = TRANSPARENT;
  let blueOpacity      = '1';
  const purpleOpacity    = '0.8';

  if (previewType === PREVIEW_TYPE.INNER_JOIN) {
    blueCircleFill   = TRANSPARENT;
    purpleCircleFill = LIGHT_PURPLE;
  } else if (previewType === PREVIEW_TYPE.MERGE_ROWS) {
    blueCircleFill   = LIGHT_BLUE;
    purpleCircleFill = LIGHT_PURPLE;
  } else {
    // FULL_OUTER
    blueCircleFill   = LIGHT_BLUE;
    purpleCircleFill = LIGHT_PURPLE;
    blueOpacity      = '0.7';
  }

  const renderCircles = (): React.JSX.Element => {
    if (previewType === PREVIEW_TYPE.INNER_JOIN) {
      return (
        <>
          <defs>
            <clipPath id="intersectionClip">
              <circle cx={585} cy={235} r={30} />
            </clipPath>
          </defs>
          {/* Blue circle — outline only */}
          <circle cx={585} cy={235} r={30} fill={TRANSPARENT} fillOpacity="1" stroke={BLUE} strokeWidth="1.5" />
          {/* Purple circle — only intersection filled */}
          <circle cx={615} cy={235} r={30} fill={LIGHT_PURPLE} clipPath="url(#intersectionClip)" />
          {/* Purple circle — outline */}
          <circle cx={615} cy={235} r={30} fill="none" fillOpacity="0" stroke={PURPLE} strokeWidth="1.5" />
        </>
      );
    }
    if (previewType === PREVIEW_TYPE.MERGE_ROWS) {
      return (
        <>
          <circle cx={600} cy={205} r={30} fill={blueCircleFill}   fillOpacity={blueOpacity}   stroke={BLUE}   strokeWidth="1.5" />
          <circle cx={600} cy={265} r={30} fill={purpleCircleFill} fillOpacity={purpleOpacity} stroke={PURPLE} strokeWidth="1.5" />
        </>
      );
    }
    // FULL_OUTER
    return (
      <>
        <defs>
          <clipPath id="intersectionClip">
            <circle cx={585} cy={235} r={30} />
          </clipPath>
        </defs>
        <circle cx={585} cy={235} r={30} fill={LIGHT_BLUE}   fillOpacity="1" stroke={BLUE}   strokeWidth="1.5" />
        <circle cx={615} cy={235} r={30} fill={LIGHT_PURPLE} clipPath="url(#intersectionClip)" stroke="none" />
        <circle cx={615} cy={235} r={30} fill={LIGHT_PURPLE} fillOpacity="1" stroke={PURPLE} strokeWidth="1.5" />
      </>
    );
  };

  return (
    <svg className={styles.connectorSvg} aria-label={intl.formatMessage(messages.diagramAriaLabel)}>
      <defs>
        <marker id="arrowhead" markerWidth="10" markerHeight="7" refX="10" refY="3.5" orient="auto" fill={GRAY}>
          <polygon points="0 0, 10 3.5, 0 7" />
        </marker>
      </defs>

      {/* Horizontal lines from table edges to connector column (x=600) */}
      <line x1={400} y1={120} x2={600} y2={120} className={styles.svgLine} />
      <line x1={400} y1={350} x2={600} y2={350} className={styles.svgLine} />

      {/* Vertical lines up/down from the connector column to the circles */}
      {previewType === PREVIEW_TYPE.MERGE_ROWS ? (
        <>
          <line x1={600} y1={120} x2={600} y2={175} className={styles.svgLine} />
          <line x1={600} y1={295} x2={600} y2={350} className={styles.svgLine} />
        </>
      ) : (
        <>
          <line x1={600} y1={120} x2={600} y2={205} className={styles.svgLine} />
          <line x1={600} y1={265} x2={600} y2={350} className={styles.svgLine} />
        </>
      )}

      {/* Circles (stacked or Venn) */}
      {renderCircles()}

      {/* Arrow from circles to merged table */}
      <line x1={630} y1={235} x2={800} y2={235} className={styles.svgLine} markerEnd="url(#arrowhead)" />
    </svg>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

interface MergingPanelBodyProps {
  controller: ElyraController;
}

export function MergingPanelBody({ controller }: MergingPanelBodyProps): React.JSX.Element {
  const intl = useIntl();
  const appData = controller.getAppData() as {
    nodeId?: string;
    pipelineFlow?: { pipelines?: Array<{ nodes?: any[] }> };
  };

  const nodeId      = appData.nodeId ?? '';
  const {pipelineFlow} = appData;

  // Read current parameter values from controller.
  // Narrow directly to MergeType / ColumnOption — avoids the double cast through string.
  const rawMergeType    = controller.getPropertyValue?.({ name: 'merge_type' })    as MergeType    | undefined;
  const rawColumnOption = controller.getPropertyValue?.({ name: 'column_option' }) as ColumnOption | undefined;

  const [mergeType,    setMergeType]    = useState<MergeType>(rawMergeType    ?? MERGE_TYPE.ROWS);
  const [columnOption, setColumnOption] = useState<ColumnOption>(rawColumnOption ?? COLUMN_OPTION.INNER_JOIN);
  // Initialise previewType to INNER_JOIN regardless of the stored merge type
  const [previewType,  setPreviewType]  = useState<PreviewType>(PREVIEW_TYPE.INNER_JOIN);
  const [isTearsheetOpen, setIsTearsheetOpen] = useState(false);

  // Reset the Save button state on unmount (runs when the panel closes or switches nodes).
  // On the next open, Elyra remounts the panel fresh. For the merge node there are no required
  // params so Save is always enabled.
  useEffect(() => () => { controller.setSaveButtonDisable(false); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Track previous values so we only fire enrichment when something actually changed
  const prevMergeTypeRef    = useRef<MergeType>(mergeType);
  const prevColumnOptionRef = useRef<ColumnOption>(columnOption);

  // Local cache of the per-node available_features returned by the last enrichment call.
  // Updated whenever merge_type or column_option changes to keep the feature buckets fresh.
  const [enrichedMergeNode, setEnrichedMergeNode] = useState<Record<string, unknown> | null>(null);

  // Call enrichFlowFeatures whenever merge_type or column_option changes.
  // This keeps available_features / output_features buckets fresh after
  // every radio / dropdown interaction without a full panel reload.
  useEffect(() => {
    const mergeTypeChanged    = mergeType    !== prevMergeTypeRef.current;
    const columnOptionChanged = columnOption !== prevColumnOptionRef.current;
    if (!mergeTypeChanged && !columnOptionChanged) { return; }

    prevMergeTypeRef.current    = mergeType;
    prevColumnOptionRef.current = columnOption;

    if (!pipelineFlow) { return; }

    const runEnrich = async (): Promise<void> => {
      try {
        // structuredClone so we never mutate the live appData reference.
        // Patch the current merge_type / column_option onto the merge node so the
        // backend always receives the live UI values — even before the user saves —
        // matching the reviewer's suggestion.
        const flowToEnrich = structuredClone(pipelineFlow);
        for (const pipeline of flowToEnrich.pipelines ?? []) {
          for (const node of pipeline.nodes ?? []) {
            if (node['id'] === nodeId) {
              const params = (node['parameters'] ?? {}) as Record<string, unknown>;
              params['merge_type']    = mergeType;
              params['column_option'] = mergeType === MERGE_TYPE.ROWS ? '' : columnOption;
              node['parameters']      = params;
            }
          }
        }
        const response = await enrichFlowFeatures(flowToEnrich as object);
        const enrichedFlow = response.data as {
          pipelines?: Array<{ nodes?: Array<{ id: string; parameters?: Record<string, unknown> }> }>;
        };

        // Find the merge node in the enriched response and store it locally.
        // Downstream consumers (e.g. VectorDB feature mapping) read from
        // appData.nodeFeatureMap which Canvas refreshes on its own save cycle;
        // here we only need to keep the merge panel itself up-to-date.
        for (const pipeline of enrichedFlow.pipelines ?? []) {
          const mergeNode = pipeline.nodes?.find((n) => n.id === nodeId);
          if (mergeNode?.parameters) {
            setEnrichedMergeNode(mergeNode.parameters);
            break;
          }
        }
      } catch {
        // Best-effort — a failed enrichment is non-critical; current state remains
      }
    };

    void runEnrich();
  }, [mergeType, columnOption]); // eslint-disable-line react-hooks/exhaustive-deps

  const updateMergeType = (value: MergeType): void => {
    setMergeType(value);
    controller.updatePropertyValue?.({ name: 'merge_type' }, value);
    if (value === MERGE_TYPE.ROWS) {
      controller.updatePropertyValue?.({ name: 'column_option' }, '');
      setPreviewType(PREVIEW_TYPE.MERGE_ROWS);
    } else {
      controller.updatePropertyValue?.({ name: 'column_option' }, columnOption);
      setPreviewType(columnOption === COLUMN_OPTION.INNER_JOIN ? PREVIEW_TYPE.INNER_JOIN : PREVIEW_TYPE.FULL_OUTER);
    }
    controller.setSaveButtonDisable(false);
  };

  const updateColumnOption = (value: ColumnOption): void => {
    setColumnOption(value);
    controller.updatePropertyValue?.({ name: 'column_option' }, value);
    setPreviewType(value === COLUMN_OPTION.INNER_JOIN ? PREVIEW_TYPE.INNER_JOIN : PREVIEW_TYPE.FULL_OUTER);
    controller.setSaveButtonDisable(false);
  };

  // Incoming link summary rows
  const incomingLinks = useMemo(() => {
    if (!pipelineFlow) { return []; }
    const nodes = (pipelineFlow.pipelines?.[0]?.nodes ?? []) as Array<Record<string, unknown>>;
    const mergingNode  = nodes.find((n) => n['id'] === nodeId);
    if (!mergingNode)  { return []; }
    const inputs = (mergingNode['inputs'] as Array<{ links?: Array<Record<string, unknown>> }> | undefined) ?? [];
    const links  = inputs.flatMap((inp) => inp.links ?? []);
    return links.map((link, idx) => {
      const sourceNode = nodes.find((n) => n['id'] === (link['node_id_ref'] as string));
      const params     = sourceNode?.['parameters'] as Record<string, unknown> | undefined;
      const uiData     = (sourceNode?.['app_data'] as Record<string, unknown> | undefined)?.['ui_data'] as Record<string, unknown> | undefined;
      const sourceLabel: string =
        (params?.['display_label'] as string | undefined) ??
        (uiData?.['label']        as string | undefined) ??
        (link['node_id_ref']      as string | undefined) ??
        '—';
      return {
        id:         (link['id'] as string | undefined) ?? String(idx),
        sourceName: sourceLabel,
        linkName:   (link['link_name'] as string | undefined) ?? '—',
      };
    });
  }, [pipelineFlow, nodeId]);

  const columnOptionItems: ColumnOption[] = [COLUMN_OPTION.INNER_JOIN, COLUMN_OPTION.FULL_OUTER];
  const columnOptionLabel = (item: ColumnOption): string =>
    item === COLUMN_OPTION.INNER_JOIN
      ? intl.formatMessage(messages.columnOptionInnerJoin)
      : intl.formatMessage(messages.columnOptionFullOuter);

  const previewItems: PreviewType[] = [PREVIEW_TYPE.MERGE_ROWS, PREVIEW_TYPE.INNER_JOIN, PREVIEW_TYPE.FULL_OUTER];
  const previewItemLabel = (item: PreviewType): string => {
    if (item === PREVIEW_TYPE.MERGE_ROWS) { return intl.formatMessage(messages.previewRows); }
    if (item === PREVIEW_TYPE.INNER_JOIN) { return intl.formatMessage(messages.previewInnerJoin); }
    return intl.formatMessage(messages.previewFullOuter);
  };

  // Derived variable — replaces the IIFE in render (react/no-unstable-nested-components).
  // Counts the output features from the last enrichment response; 0 when not yet loaded.
  const outputFeatureCount = enrichedMergeNode !== null
    ? Object.keys((enrichedMergeNode.output_features as Record<string, unknown> | undefined) ?? {}).length
    : 0;

  return (
    <div className={styles.panelContainer}>

      {/* ── Merge type ──────────────────────────────────────────────────────── */}
      <div className={styles.formField}>
        <p className={styles.fieldLabel}>{intl.formatMessage(messages.mergeType)}</p>
        <p className={styles.fieldHint}>{intl.formatMessage(messages.mergeTypeHint)}</p>

        <div className={styles.radioButtonGroup}>
          <div className={styles.radioOption}>
            <RadioButton
              id="merge-rows"
              name="mergeTypeGroupRows"
              labelText={intl.formatMessage(messages.mergeRowsLabel)}
              value={MERGE_TYPE.ROWS}
              checked={mergeType === MERGE_TYPE.ROWS}
              onChange={() => { updateMergeType(MERGE_TYPE.ROWS); }}
            />
          </div>
          <div className={styles.radioOption}>
            <RadioButton
              id="merge-columns"
              name="mergeTypeGroupColumns"
              labelText={intl.formatMessage(messages.mergeColumnsLabel)}
              value={MERGE_TYPE.COLUMNS}
              checked={mergeType === MERGE_TYPE.COLUMNS}
              onChange={() => { updateMergeType(MERGE_TYPE.COLUMNS); }}
            />
          </div>
        </div>

        {mergeType === MERGE_TYPE.COLUMNS && (
          <div className={styles.combineColumnsContent}>
            <div className={styles.formField}>
              <Dropdown
                id="merge-column-option"
                titleText={intl.formatMessage(messages.columnMergeOptionTitle)}
                label={intl.formatMessage(messages.selectJoinType)}
                hideLabel
                selectedItem={columnOption}
                items={columnOptionItems}
                itemToString={columnOptionLabel}
                onChange={({ selectedItem }) => {
                  if (selectedItem) { updateColumnOption(selectedItem); }
                }}
              />
            </div>
            <div className={styles.formField}>
              <InlineNotification
                kind="info"
                lowContrast
                hideCloseButton
                title={intl.formatMessage(messages.columnNoteTitle)}
                subtitle={intl.formatMessage(messages.columnNoteSubtitle)}
              />
            </div>
          </div>
        )}
      </div>

      {/* ── Preview button */}
      <div className={styles.mergePreviewSection}>
        <div className={styles.selectButtonWrapper}>
          <Button
            kind="ghost"
            size="sm"
            onClick={() => { setIsTearsheetOpen(true); }}
            className={styles.selectButton}
            disabled={!mergeType}
          >
            {intl.formatMessage(messages.previewButton)}
          </Button>
        </div>
      </div>

      {/* ── Preview tearsheet */}
      <Tearsheet
        open={isTearsheetOpen}
        onClose={() => { setIsTearsheetOpen(false); }}
        hasCloseIcon
        closeIconDescription={intl.formatMessage(messages.close)}
        title={intl.formatMessage(messages.previewTearsheetTitle)}
        description={intl.formatMessage(messages.previewTearsheetDesc)}
      >
        <div className={styles.tearsheetTableWrapper}>
          {/* Preview type selector */}
          <div className={styles.previewSelectContainer}>
            <Dropdown
              id="merge-preview-type"
              titleText={intl.formatMessage(messages.previewDropdownTitle)}
              label={intl.formatMessage(messages.previewDropdownLabel)}
              selectedItem={previewType}
              items={previewItems}
              itemToString={previewItemLabel}
              className={styles.fullWidthSelect}
              onChange={({ selectedItem }) => {
                if (selectedItem) { setPreviewType(selectedItem); }
              }}
            />
          </div>

          {previewType === PREVIEW_TYPE.MERGE_ROWS && (
            <p className={styles.noteText}>
              {intl.formatMessage(messages.previewRowsNote)}
            </p>
          )}
          <p className={styles.disclaimerText}>
            {intl.formatMessage(messages.previewDisclaimer)}
          </p>

          {/* Diagram wrapper */}
          <div className={styles.diagramWrapper}>
            {/* Absolute SVG overlay */}
            <DiagramSvg previewType={previewType} />

            {/* Table layout */}
            <div className={styles.mergePreviewLayout}>
              {/* Left column: two branch tables stacked */}
              <div className={styles.inputTables}>
                <div className={styles.tableAlignment}>
                  <PreviewTable
                    title={intl.formatMessage(messages.inputFromBranch1)}
                    headers={[
                      intl.formatMessage(messages.headerDocId),
                      intl.formatMessage(messages.headerName),
                      intl.formatMessage(messages.headerAuthor),
                      intl.formatMessage(messages.headerLanguage),
                    ]}
                    rows={[
                      [D.row1, D.doc1, D.alice,   D.english],
                      [D.row2, D.doc2, D.bob,     D.german],
                      [D.row4, D.doc4, D.charlie, D.french],
                    ]}
                    tableType="branch1"
                  />

                  {previewType === PREVIEW_TYPE.MERGE_ROWS ? (
                    <PreviewTable
                      title={intl.formatMessage(messages.inputFromBranch2)}
                      headers={[
                        intl.formatMessage(messages.headerDocId),
                        intl.formatMessage(messages.headerName),
                        intl.formatMessage(messages.headerQuality),
                        intl.formatMessage(messages.headerLanguage),
                      ]}
                      rows={[[D.row5, D.doc9, D.q4, D.english]]}
                      tableType="branch2"
                      className="merge-rows-branch2 branch2-table"
                    />
                  ) : (
                    <PreviewTable
                      title={intl.formatMessage(messages.inputFromBranch2)}
                      headers={[
                        intl.formatMessage(messages.headerDocId),
                        intl.formatMessage(messages.headerName),
                        intl.formatMessage(messages.headerQuality),
                      ]}
                      rows={[
                        [D.row1, D.doc1, D.q1],
                        [D.row2, D.doc2, D.q2],
                        [D.row3, D.doc4, D.q3],
                      ]}
                      tableType="branch2"
                    />
                  )}
                </div>
              </div>

              {/* Right column: merged output table */}
              <div className={styles.mergedTableContainer}>
                <MergedTablePreview previewType={previewType} />
              </div>
            </div>
          </div>
        </div>
      </Tearsheet>

      {/* ── Live output feature count — updates after each enrichment call ── */}
      {outputFeatureCount > 0 && (
        <p className={styles.fieldHint}>
          {intl.formatMessage(messages.outputFeaturesCount, { count: outputFeatureCount })}
        </p>
      )}

      {/* ── Incoming link summary ──────────────────────────────────────────── */}
      {incomingLinks.length > 0 && (
        <div className={styles.linkSummary}>
          <p className={styles.fieldLabel}>{intl.formatMessage(messages.incomingLinks)}</p>
          <TableContainer>
            <Table size="sm">
              <TableHead>
                <TableRow>
                  <TableHeader>{intl.formatMessage(messages.sourceNode)}</TableHeader>
                  <TableHeader>{intl.formatMessage(messages.linkName)}</TableHeader>
                </TableRow>
              </TableHead>
              <TableBody>
                {incomingLinks.map((row) => (
                  <TableRow key={row.id}>
                    <TableCell>{row.sourceName}</TableCell>
                    <TableCell>{row.linkName}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TableContainer>
        </div>
      )}

    </div>
  );
}
