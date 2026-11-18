/**
 * Canvas action constants for Elyra Canvas toolbar and edit actions
 *
 * @module constants/canvasActions
 *
 * @remarks
 * These action strings are used in:
 * - Toolbar button configurations
 * - Context menu items
 * - Edit action handlers
 * - Click action handlers
 *
 * Action names must match Elyra Canvas's expected action identifiers
 * for built-in actions (undo, redo, cut, copy, paste, etc.).
 * Custom actions (save, run) are handled by the editActionHandler.
 */

import { JOB_RUN_STATUS } from '@/constants/jobRunStatus';

/**
 * Canvas action identifiers for toolbar buttons, context menus, and handlers.
 *
 * @constant
 */
export const CANVAS_ACTIONS = {
  /**
   * Fired by Elyra when a node is created programmatically (e.g. via API).
   * For palette drags, Elyra fires CREATE_AUTO_NODE instead.
   */
  CREATE_NODE: 'createNode',
  /**
   * Fired by Elyra when a node is dragged from the palette onto the canvas.
   * Automatically links to the last selected node when one is available.
   * This is the action triggered by all normal palette-to-canvas drops.
   */
  CREATE_AUTO_NODE: 'createAutoNode',

  /** Toggle palette visibility */
  PALETTE: 'palette',

  /** Undo last action */
  UNDO: 'undo',

  /** Redo last undone action */
  REDO: 'redo',

  /** Cut selected nodes to clipboard */
  CUT: 'cut',

  /** Copy selected nodes to clipboard */
  COPY: 'copy',

  /** Paste nodes from clipboard */
  PASTE: 'paste',

  /** Delete selected nodes and comments */
  DELETE: 'deleteSelectedObjects',

  /** Edit node properties (custom action) */
  EDIT_NODE: 'editNode',

  /** Edit comment text (custom action) */
  EDIT_COMMENT: 'editComment',

  /** Create a new comment on canvas */
  CREATE_COMMENT: 'createAutoComment',

  /** Zoom in on canvas */
  ZOOM_IN: 'zoomIn',

  /** Zoom out on canvas */
  ZOOM_OUT: 'zoomOut',

  /** Fit entire canvas to viewport */
  ZOOM_TO_FIT: 'zoomToFit',

  /** Save pipeline (custom action) */
  SAVE: 'save',

  /** Open Flow Run Properties tearsheet (custom action) */
  FLOW_PROPERTIES: 'flowProperties',

  /** Run pipeline (custom action) */
  RUN: 'run',

  /** Toggle the right-side logs/node-summary panel */
  TOGGLE_RIGHT_PANEL: 'toggle-right-panel',

  /** Back button in the read-only canvas toolbar */
  BACK_BUTTON: 'backButton',

  /** Read-only mode tag in the read-only canvas toolbar */
  READ_ONLY_TAG: 'readOnlyTag',

  // ── Branching / link condition actions ────────────────────────────────────

  /**
   * Add a link condition (name + criteria) on a branching or merging link.
   * Triggered from the link's context toolbar or when clicking the AddFilled
   * decoration on a link that has no condition yet.
   */
  ADD_CONDITION: 'addCondition',

  /**
   * Edit an existing link condition.
   * Triggered from the link context menu when the link already has a condition.
   */
  EDIT_CONDITION: 'editCondition',

  /**
   * Remove only the condition (name + criteria) from a link while keeping the
   * link itself in the pipeline.
   */
  DELETE_CONDITION: 'deleteCondition',

  /** Delete a link (the canvas edge) entirely. */
  DELETE_LINK: 'deleteLink',

  /**
   * Open the "Recommended next nodes" suggestion card for the selected node.
   * Triggered from the node context toolbar (Playlist icon).
   */
  RECOMMEND_NODES: 'recommendNodes',
} as const;

/**
 * Type representing valid canvas action values
 */
export type CanvasAction = typeof CANVAS_ACTIONS[keyof typeof CANVAS_ACTIONS];

// ── Job run asset reference ───────────────────────────────────────────────────

/** asset_ref_type value used when creating a job run for a UDP flow. */
export const JOB_ASSET_REF_TYPE = 'ibm_udp_flow';

// ── Node decoration config ────────────────────────────────────────────────────

/** Shared position / size config applied to every node status decoration. */
export const NODE_DECORATION_POS = {
  position: 'middleRight' as const,
  y_pos: -30,
  height: 20,
  width: 20,
  outline: false,
  temporary: true,
} as const;

/** Node statuses that map to the warning decoration icon.
 *  Values are pre-lowercased so callers can compare with `.toLowerCase()` safely. */
export const WARNING_NODE_STATUSES = new Set([
  JOB_RUN_STATUS.WARNING,
  JOB_RUN_STATUS.COMPLETED_WITH_ERRORS,
  JOB_RUN_STATUS.COMPLETED_WITH_WARNINGS,
  JOB_RUN_STATUS.SKIPPED,
].map((s) => s.toLowerCase()));
