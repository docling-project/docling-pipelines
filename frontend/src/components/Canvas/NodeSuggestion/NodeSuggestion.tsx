import React, { useState, useMemo, useCallback, useId } from 'react';
import { Close, ChevronDown, ChevronUp } from '@carbon/icons-react';
import { Search, Button } from '@carbon/react';
import { useIntl } from 'react-intl';
import type { PaletteData } from '@/types/palette';
import { messages } from './NodeSuggestion.messages';
import styles from './NodeSuggestion.module.scss';

// ─── Types ────────────────────────────────────────────────────────────────────

interface SuggestionNode {
  id: string;
  op: string;
  label: string;
  description?: string;
}

interface SuggestionCategory {
  id: string;
  label: string;
  image?: string;
  nodes: SuggestionNode[];
}

export interface NodeSuggestionProps {
  /** Close the panel without creating any node. */
  onClose: () => void;
  /** Called with the selected operator's op-code. */
  onSelectNode: (nodeOp: string) => void;
  /** Screen-pixel position (card top-left corner). */
  position: { x: number; y: number };
  /** Pre-filtered palette: only valid successors for the source node are present. */
  paletteData: PaletteData;
  /** Connector line start — node right-centre in screen px. */
  lineStart?: { x: number; y: number } | null;
  /** Connector line end — card left-centre in screen px. */
  lineEnd?: { x: number; y: number } | null;
}

// ─── Connector SVG ────────────────────────────────────────────────────────────

/** Size of the dragStateArrow.svg image in screen pixels (matches ElyraCanvas port size). */
const ARROW_SIZE = 20;

/**
 * Fixed-position overlay that draws the dashed horizontal line and the
 * drag-arrow image (dragStateArrow.svg) between the source node and the
 * suggestion card.
 *
 * Line spec (Figma): 1px stroke, dash 2 2, colour #0F62FE.
 * Arrow: public/images/decorations/dragStateArrow.svg placed at the line end.
 */
function NodeSuggestionConnector({
  start, end,
}: {
  start: { x: number; y: number };
  end:   { x: number; y: number };
}): React.JSX.Element {
  // Arrow sits flush against the card left edge: right edge of image = end.x.
  const arrowLeft = end.x - ARROW_SIZE;
  const arrowTop  = end.y - ARROW_SIZE / 2;

  // Dashed line runs from source node right-edge to the left edge of the arrow.
  const lineEndX = arrowLeft;

  return (
    <>
      {/* Dashed line — Figma spec: 1px stroke, dash 2 2, #0F62FE */}
      <svg
        style={{
          position: 'fixed',
          left: start.x,
          top: start.y,
          width: Math.max(0, lineEndX - start.x),
          height: 1,
          pointerEvents: 'none',
          zIndex: 9998,
          overflow: 'visible',
        }}
        aria-hidden="true"
      >
        <line
          x1={0} y1={0} x2={Math.max(0, lineEndX - start.x)} y2={0}
          stroke="#0f62fe" strokeWidth={1}
          strokeDasharray="2 2" strokeLinecap="round"
        />
      </svg>
      {/* Arrow image */}
      <img
        src="/ui/images/decorations/dragStateArrow.svg"
        alt=""
        aria-hidden="true"
        style={{
          position: 'fixed',
          left: arrowLeft,
          top: arrowTop,
          width: ARROW_SIZE,
          height: ARROW_SIZE,
          pointerEvents: 'none',
          zIndex: 9998,
        }}
      />
    </>
  );
}

// ─── Component ────────────────────────────────────────────────────────────────

const NodeSuggestion: React.FC<NodeSuggestionProps> = ({
  onClose,
  onSelectNode,
  position,
  paletteData,
  lineStart,
  lineEnd,
}) => {
  const intl = useIntl();
  const uid = useId();
  const [searchTerm, setSearchTerm] = useState('');

  // Reshape the pre-filtered paletteData into display-friendly categories.
  // The palette is already filtered to valid successors — this memo only reshapes.
  const suggestions = useMemo<SuggestionCategory[]>(() => {
    if (!paletteData?.categories) {return [];}
    return paletteData.categories
      .map((category) => ({
        id: category.id,
        label: category.label ?? category.id,
        // `image` is not part of PaletteCategory — Elyra may inject it at runtime.
        // eslint-disable-next-line @typescript-eslint/no-explicit-any, @typescript-eslint/no-unsafe-member-access
        image: (category as any).image as string | undefined,
        nodes: (category.node_types ?? []).map((nodeType) => ({
          id: nodeType.id,
          op: nodeType.op,
          label: nodeType.app_data?.ui_data?.label ?? nodeType.id,
          description: nodeType.app_data?.ui_data?.description,
        })),
      }))
      .filter((c) => c.nodes.length > 0);
  }, [paletteData]);

  // All categories start expanded.
  // expandedCategories tracks manually collapsed ones — a category id present
  // here means it was explicitly collapsed by the user.
  const [collapsedCategories, setCollapsedCategories] = useState<Set<string>>(new Set());

  // Secondary filter by the user's search string.
  const filteredSuggestions = useMemo<SuggestionCategory[]>(() => {
    if (!searchTerm.trim()) {return suggestions;}
    const lower = searchTerm.toLowerCase();
    return suggestions
      .map((category) => ({
        ...category,
        nodes: category.nodes.filter((n) => n.label.toLowerCase().includes(lower)),
      }))
      .filter((c) => c.nodes.length > 0);
  }, [suggestions, searchTerm]);

  const toggleCategory = useCallback((categoryId: string) => {
    setCollapsedCategories((prev) => {
      const next = new Set(prev);
      if (next.has(categoryId)) {
        next.delete(categoryId);   // was collapsed → expand
      } else {
        next.add(categoryId);      // was expanded  → collapse
      }
      return next;
    });
  }, []);

  const handleNodeClick = useCallback(
    (nodeOp: string) => {
      onSelectNode(nodeOp);
      onClose();
    },
    [onSelectNode, onClose]
  );

  return (
    <>
      {lineStart && lineEnd && (
        <NodeSuggestionConnector start={lineStart} end={lineEnd} />
      )}
      <div
        className={styles.card}
        style={{ left: `${position.x}px`, top: `${position.y}px` }}
        role="dialog"
        aria-label={intl.formatMessage(messages.ariaLabel)}
        aria-modal="false"
      >
        {/* ── Header ── */}
        <div className={styles.header}>
          <div className={styles.headerText}>
            <span className={styles.title}>{intl.formatMessage(messages.title)}</span>
            <span className={styles.subtitle}>
              {intl.formatMessage(messages.subtitle)}
            </span>
          </div>
          <Button
            kind="ghost"
            size="xs"
            hasIconOnly
            renderIcon={Close}
            iconDescription={intl.formatMessage(messages.closeDescription)}
            tooltipPosition="left"
            onClick={onClose}
            className={styles.closeButton}
          />
        </div>

        {/* ── Search ── */}
        <div className={styles.search}>
          <Search
            id={`node-suggestion-search-${uid}`}
            labelText=""
            placeholder={intl.formatMessage(messages.searchPlaceholder)}
            value={searchTerm}
            onChange={(e: React.ChangeEvent<HTMLInputElement>) => { setSearchTerm(e.target.value); }}
            size="sm"
            className={styles.searchInput}
          />
        </div>

        {/* ── Categories ── */}
        <div className={styles.categories}>
          {filteredSuggestions.length === 0 ? (
            <div className={styles.empty}>
              {searchTerm ? intl.formatMessage(messages.noMatchingNodes) : intl.formatMessage(messages.noSuggestionsAvailable)}
            </div>
          ) : (
            filteredSuggestions.map((category) => (
              <div key={category.id} className={styles.category}>
                <button
                  type="button"
                  className={styles.categoryHeader}
                  onClick={() => { toggleCategory(category.id); }}
                  aria-expanded={!collapsedCategories.has(category.id)}
                >
                  <div className={styles.categoryLabel}>
                    {category.image && (
                      <img
                        src={category.image}
                        alt=""
                        className={styles.categoryIcon}
                        width={16}
                        height={16}
                      />
                    )}
                    <span>{category.label}</span>
                  </div>
                  {!collapsedCategories.has(category.id)
                    ? <ChevronUp size={16} />
                    : <ChevronDown size={16} />}
                </button>

                {!collapsedCategories.has(category.id) && (
                  <div className={styles.nodes}>
                    {category.nodes.map((node) => (
                      <button
                        key={node.id}
                        type="button"
                        className={styles.node}
                        onClick={() => { handleNodeClick(node.op); }}
                        title={node.description}
                      >
                        {node.label}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            ))
          )}
        </div>
      </div>
    </>
  );
};

export default NodeSuggestion;
