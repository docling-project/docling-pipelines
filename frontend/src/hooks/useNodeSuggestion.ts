/* eslint-disable @typescript-eslint/no-unsafe-assignment */
/* eslint-disable @typescript-eslint/no-unsafe-member-access */
/* eslint-disable @typescript-eslint/no-explicit-any */
/* eslint-disable @typescript-eslint/no-unsafe-return */

/* eslint-disable @typescript-eslint/no-unsafe-call */
import { useState, useCallback, useEffect, useRef } from 'react';
import type { PaletteData } from '@/types/palette';
import { getSuccessorOps, NODE_SUGGESTION_STEP_X } from '@/constants/nodeSuggestion';
import { log4js, logUtil } from '@/utils/logger';

const logger = log4js.getLogger('useNodeSuggestion');

// ── Types ─────────────────────────────────────────────────────────────────────

export interface NodeSuggestionState {
  position:     { x: number; y: number };
  lineStart:    { x: number; y: number };
  lineEnd:      { x: number; y: number };
  paletteData:  PaletteData;
  sourceNodeId: string;
}

// ── Pure helpers ──────────────────────────────────────────────────────────────

/**
 * Converts a node's logical canvas position to the screen-pixel coordinates
 * needed for the NodeSuggestion card and the dashed connector line.
 *
 * Uses the canvas zoom transform (getZoom) + node.x_pos / y_pos directly —
 * no DOM query needed.
 *
 * Returns:
 *  cardPos   — screen position of the card top-left corner
 *  lineStart — screen position of the node's right-centre (connector start)
 *  lineEnd   — screen position of the card's left-centre (connector end)
 */
function getNodeSuggestionLayout(
  node: any,
  canvasController: any
): {
  cardPos:   { x: number; y: number };
  lineStart: { x: number; y: number };
  lineEnd:   { x: number; y: number };
} | null {
  try {
    const canvasEl = document.querySelector('.d3-svg-background');
    if (!canvasEl) { return null; }
    const origin = canvasEl.getBoundingClientRect();

    const t  = (canvasController.getZoom?.() ?? {}) as { x?: number; y?: number; k?: number };
    const k  = t.k  ?? 1;
    const tx = t.x  ?? 0;
    const ty = t.y  ?? 0;

    const nodeX = node.x_pos as number;
    const nodeY = node.y_pos as number;
    const nodeW = (node.width  as number | undefined) ?? 208;
    const nodeH = (node.height as number | undefined) ?? 68;

    const screenNodeLeft    = origin.left + tx + nodeX * k;
    const screenNodeTop     = origin.top  + ty + nodeY * k;
    const screenNodeRight   = screenNodeLeft + nodeW * k;
    const screenNodeCentreY = screenNodeTop + (nodeH * k) / 2;

    const cardCanvasX = nodeX + nodeW + NODE_SUGGESTION_STEP_X;
    const cardScreenX = origin.left + tx + cardCanvasX * k;
    const cardScreenY = screenNodeTop;

    return {
      cardPos:   { x: cardScreenX, y: cardScreenY },
      lineStart: { x: screenNodeRight, y: screenNodeCentreY },
      lineEnd:   { x: cardScreenX,     y: screenNodeCentreY },
    };
  } catch {
    return null;
  }
}

/**
 * Returns a shallow copy of paletteData whose categories contain only the
 * node_types whose op-code appears in allowedOps.
 * Categories with no matching nodes are dropped entirely.
 */
function filterPaletteByOps(paletteData: any, allowedOps: Set<string>): any {
  if (!paletteData?.categories) { return paletteData; }
  const categories = (paletteData.categories as any[])
    .map((cat: any) => ({
      ...cat,
      node_types: ((cat.node_types as any[] | undefined) ?? []).filter(
        (n: any) => allowedOps.has(n.op as string)
      ),
    }))
    .filter((cat: any) => (cat.node_types as any[]).length > 0);
  return { ...paletteData, categories };
}

/**
 * Returns the set of op-codes already present anywhere in the current pipeline
 * flow (excluding the source node itself).
 * Used to exclude already-added operators from the suggestion palette so the
 * user is never suggested a node that already exists in the flow.
 */
function getAlreadyConnectedOps(sourceNodeId: string, canvasController: any): Set<string> {
  const flow = canvasController.getPipelineFlow?.();
  const nodes: any[] = flow?.pipelines?.[0]?.nodes ?? [];
  const presentOps = new Set<string>();
  nodes.forEach((node: any) => {
    if (node.id !== sourceNodeId && node.op) {
      presentOps.add(node.op as string);
    }
  });
  return presentOps;
}

/**
 * Returns true if any node in the current pipeline has an input link that
 * references the given source node (i.e. the source already has an outgoing link).
 */
function hasOutgoingLink(sourceNodeId: string, canvasController: any): boolean {
  const flow = canvasController.getPipelineFlow?.();
  const nodes: any[] = flow?.pipelines?.[0]?.nodes ?? [];
  return nodes.some((node: any) =>
    ((node.inputs as any[] | undefined) ?? []).some((input: any) =>
      ((input.links as any[] | undefined) ?? []).some(
        (link: any) => link.node_id_ref === sourceNodeId
      )
    )
  );
}

/**
 * Builds the NodeSuggestionState for a given node, filtering the palette to
 * valid successors minus operators already present in the flow.
 * Returns null if the layout cannot be computed (e.g. canvas not yet mounted).
 */
function buildNodeSuggestion(
  nodeId: string,
  canvasController: any
): NodeSuggestionState | null {
  const node = canvasController.getNode(nodeId);
  if (!node) { return null; }
  if (hasOutgoingLink(nodeId, canvasController)) { return null; }

  const layout = getNodeSuggestionLayout(node, canvasController);
  if (!layout) { return null; }
  const fullPalette = canvasController.getPaletteData();
  const successorOps = getSuccessorOps(node.op as string);
  const alreadyConnected = getAlreadyConnectedOps(nodeId, canvasController);
  alreadyConnected.forEach((op) => { successorOps.delete(op); });
  const paletteData = filterPaletteByOps(fullPalette, successorOps);
  return {
    position:     layout.cardPos,
    lineStart:    layout.lineStart,
    lineEnd:      layout.lineEnd,
    paletteData,
    sourceNodeId: nodeId,
  };
}

// ── Hook ──────────────────────────────────────────────────────────────────────

export interface UseNodeSuggestionReturn {
  /** Current suggestion panel state — null means the panel is closed. */
  nodeSuggestion: NodeSuggestionState | null;
  /** Open the suggestion panel for the given node using the canvas controller. */
  openNodeSuggestion: (nodeId: string, canvasController: any) => void;
  /** Close the suggestion panel. */
  handleNodeSuggestionClose: () => void;
  /**
   * Handle the user selecting a node op from the suggestion panel.
   * Dispatches createAutoNode through the canvas controller's edit-action pipeline.
   */
  handleNodeSuggestionSelect: (nodeOp: string, canvasController: any) => void;
}

/**
 * Encapsulates all state and handlers for the NodeSuggestion panel.
 * Keeps the Canvas component free of suggestion-specific logic.
 */
export function useNodeSuggestion(): UseNodeSuggestionReturn {
  const [nodeSuggestion, setNodeSuggestion] = useState<NodeSuggestionState | null>(null);

  const handleNodeSuggestionClose = useCallback(() => {
    setNodeSuggestion(null);
  }, []);

  const openNodeSuggestion = useCallback(
    (nodeId: string, canvasController: any) => {
      const suggestion = buildNodeSuggestion(nodeId, canvasController);
      if (suggestion) { setNodeSuggestion(suggestion); }
    },
    []
  );

  const handleNodeSuggestionSelect = useCallback(
    (nodeOp: string, canvasController: any) => {
      if (!canvasController) { return; }
      // Read the latest sourceNodeId via a ref so this callback never stales.
      // (nodeSuggestion is captured via the ref below.)
      try {
        const nodeTemplate = canvasController.getPaletteNode(nodeOp);
        if (!nodeTemplate) {
          logUtil.error({ logger, message: 'Node template not found for op', data: { nodeOp } });
          return;
        }
        // sourceNodeId is read from state inside the setter to always be current.
        setNodeSuggestion((current) => {
          if (current?.sourceNodeId) {
            canvasController.setSelections([current.sourceNodeId]);
            const pipelineId = canvasController.getCurrentPipelineId();
            (canvasController).editActionHandler({
              editType: 'createAutoNode',
              editSource: 'canvas',
              addLink: true,
              nodeTemplate,
              pipelineId,
            });
          }
          return null; // close the panel
        });
      } catch (err) {
        logUtil.error({ logger, message: 'Error creating node from suggestion', data: err });
        handleNodeSuggestionClose();
      }
    },
    [handleNodeSuggestionClose]
  );

  // Close the suggestion panel when the user interacts with the canvas
  // (pan / zoom / click away).
  const handleNodeSuggestionCloseRef = useRef(handleNodeSuggestionClose);
  handleNodeSuggestionCloseRef.current = handleNodeSuggestionClose;

  useEffect(() => {
    if (!nodeSuggestion) { return; }
    const close = (): void => { handleNodeSuggestionCloseRef.current(); };
    const closeOnOutsidePointerDown = (e: PointerEvent): void => {
      const target = e.target as Element | null;
      if (target?.closest?.('[data-node-suggestion]')) { return; }
      close();
    };
    // Capture phase so this runs before the canvas library can stop the event.
    document.addEventListener('pointerdown', closeOnOutsidePointerDown, true);
    const canvasEl = document.querySelector('.d3-svg-background');
    canvasEl?.addEventListener('wheel', close, { passive: true });
    return () => {
      document.removeEventListener('pointerdown', closeOnOutsidePointerDown, true);
      canvasEl?.removeEventListener('wheel', close);
    };
  }, [nodeSuggestion]);

  return {
    nodeSuggestion,
    openNodeSuggestion,
    handleNodeSuggestionClose,
    handleNodeSuggestionSelect,
  };
}
