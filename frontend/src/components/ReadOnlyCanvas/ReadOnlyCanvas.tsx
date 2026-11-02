/**
 * @fileoverview Read-only canvas view for displaying pipeline execution status.
 * Shows the pipeline graph with live node status decorations, run statistics panel,
 * and detailed logs/node summary panel on the right.
 *
 * Poll lifecycle lives in Canvas.tsx so polling continues in the background even
 * when the user navigates back to the edit canvas. This component is a pure
 * display component — it renders whatever is in Redux executionLogs.
 */

import React, { useEffect, useRef, useState, useCallback, useMemo } from 'react';
import { useDispatch } from 'react-redux';
import { useIntl } from 'react-intl';
import { useAppSelector } from '@/hooks';
import type { PipelineFlowDef, CanvasController, CanvasConfig } from '@elyra/canvas';
import { applyAllLinkDecorations } from '@/utils/linkDecorations';
import {
  CheckmarkFilled,
  ErrorFilled,
  WarningAltFilled,
  EditOff,
  OpenPanelFilledRight,
  RightPanelCloseFilled,
  ArrowLeft,
} from '@carbon/icons-react';
import { InlineLoading } from '@carbon/react';
import { ElyraCanvas } from '@/components/ElyraCanvas/ElyraCanvas';
import { RunStatusTopPanel } from './RunStatusTopPanel';
import { RunSidePanel } from './RunSidePanel';
import { createJobRun } from '@/services/api/actions/job-run-actions';
import {
  setExecutionLogs,
} from '@/slices/jobRunSlice';
import { selectExecutionLogs, selectIsRunning } from '@/selectors/jobRunSelectors';
import {
  JOB_RUN_STATUS,
  COMPLETED_STATUSES,
  RUNNING_STATUSES,
  STOP_DISABLED_STATUSES,
} from '@/constants/jobRunStatus';
import {
  CANVAS_ACTIONS,
  JOB_ASSET_REF_TYPE,
  NODE_DECORATION_POS,
  WARNING_NODE_STATUSES,
} from '@/constants/canvasActions';
import type { AppDispatch } from '@/store';
import type { JobStats } from '@/types';
import { messages } from './ReadOnlyCanvas.messages';
import styles from './ReadOnlyCanvas.module.scss';

interface ReadOnlyCanvasProps {
  pipelineFlow: PipelineFlowDef;
  jobId: string;
  jobRunId: string;
  onExit: () => void;
  /** Called by Run Again after creating a new job run — passes the new jobRunId up to Canvas. */
  onRunAgain: (newJobRunId: string) => void;
  /** Called by Stop — Canvas owns the cancel + re-poll logic. */
  onStop: () => void;
}

export function ReadOnlyCanvas({
  pipelineFlow,
  jobId,
  jobRunId,
  onExit,
  onRunAgain,
  onStop,
}: ReadOnlyCanvasProps): React.JSX.Element {
  const intl = useIntl();
  const dispatch = useDispatch<AppDispatch>();
  const executionLogs = useAppSelector(selectExecutionLogs);
  const isRunning = useAppSelector(selectIsRunning);
  const logsMatchCurrentRun = executionLogs?.job_stats?.job_run_id === jobRunId;

  // Placeholder JobStats shown immediately on mount before the first poll returns.
  // Ensures the top panel renders at mount-time rather than appearing on the fly
  // after the first poll (which can take up to 10 s).
  const PLACEHOLDER_JOB_STATS: JobStats = useMemo(() => ({
    job_id: jobId,
    job_run_id: jobRunId,
    status: JOB_RUN_STATUS.STARTING,
    message: '',
    start_time: 0,
    end_time: 0,
    duration: 0,
    heartbeat_timestamp: null,
    total_docs: 0,
    processed_docs: 0,
    completed_docs: null,
    failed_docs: 0,
    skipped_docs: 0,
    deleted_doc_count: 0,
    total_pages_processed: 0,
    page_type_stats: null,
    execution_time: null,
    orchestrator: '',
    container_kind: null,
    container_id: null,
    flow_id: null,
    user_id: null,
    account_id: null,
    user_entitlements: null,
    report_status: null,
    report_generation_started_at: null,
    report_generation_completed_at: null,
    node_stats: {},
    batch_node_stats: {},
  }), [jobId, jobRunId]);

  // Only use live data if it belongs to THIS run — stale logs from a prior run
  // must not be displayed while the new run's first poll is still in-flight.
  const displayJobStats = (logsMatchCurrentRun && executionLogs?.job_stats)
    ? executionLogs.job_stats
    : PLACEHOLDER_JOB_STATS;

  const [isMinimized, setIsMinimized] = useState(false);
  const [logsPanelVisible, setLogsPanelVisible] = useState(false);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [activeTabIndex, setActiveTabIndex] = useState(0);
  // Initial stop-button state: only trust executionLogs if they belong to THIS run.
  // Stale logs from a previous run must not set the wrong disabled state.
  const knownStatusAtMount = logsMatchCurrentRun ? (executionLogs?.job_stats?.status ?? null) : null;
  const [isStopDisabled, setIsStopDisabled] = useState(
    knownStatusAtMount !== null
      ? STOP_DISABLED_STATUSES.has(knownStatusAtMount)
      : true
  );
  // pendingDecorationsRef holds the most-recent JobStats whose decorations could not
  // be applied because the canvas controller wasn't ready yet (first-render race).
  const pendingDecorationsRef = useRef<JobStats | null>(null);
  const canvasControllerRef = useRef<CanvasController | null>(null);

  const applyNodeDecorations = useCallback((jobStats: JobStats): void => {
    const controller = canvasControllerRef.current;
    if (!controller) {
      // Controller not ready yet (ElyraCanvas hasn't fired onCanvasControllerReady).
      // Park the data so the controller-ready callback can apply it immediately after mount.
      pendingDecorationsRef.current = jobStats;
      return;
    }

    controller.getNodes().forEach((node: { id: string }) => {
      const stat = jobStats.node_stats[node.id];
      const status = stat?.node_status?.toLowerCase();

      let jsx: React.ReactNode = null;
      if (!stat) {
        jsx = RUNNING_STATUSES.has(jobStats.status) ? <InlineLoading status="active" className={styles.nodeLevelSpinner} /> : null;
      } else if (status === JOB_RUN_STATUS.COMPLETED.toLowerCase()) {
        jsx = <CheckmarkFilled size={20} className={styles.checkmarkFilled} />;
      } else if (status === JOB_RUN_STATUS.FAILED.toLowerCase()) {
        jsx = <ErrorFilled size={20} className={styles.errorFilled} />;
      } else if (WARNING_NODE_STATUSES.has(status ?? '')) {
        jsx = <WarningAltFilled size={20} className={styles.warningAltFilled} />;
      } else if (status === JOB_RUN_STATUS.RUNNING.toLowerCase()) {
        jsx = <InlineLoading status="active" className={styles.nodeLevelSpinner} />;
      }

      controller.setNodeDecorations(node.id, jsx ? [{ id: 'status', jsx, ...NODE_DECORATION_POS }] : []);
    });
  }, []);

  // Clear all node status decorations
  const clearNodeDecorations = useCallback(() => {
    const controller = canvasControllerRef.current;
    if (!controller) { return; }
    controller.getNodes().forEach((node: { id: string }) => {
      controller.setNodeDecorations(node.id, []);
    });
  }, []);

  // Once the canvas controller is registered (onCanvasControllerReady fires), drain
  // any decorations that were computed before the controller was ready, and apply
  // link-name pill decorations (read-only: no Add icon, pills non-clickable).
  const handleCanvasControllerReady = useCallback((ctrl: CanvasController) => {
    canvasControllerRef.current = ctrl;
    if (pendingDecorationsRef.current) {
      applyNodeDecorations(pendingDecorationsRef.current);
      pendingDecorationsRef.current = null;
    }
    // Defer until after Elyra's D3 layout has rendered so link elements exist in the DOM.
    requestAnimationFrame(() => { applyAllLinkDecorations(ctrl, true); });
  }, [applyNodeDecorations]);

  // React to every new poll result dispatched by Canvas's background poll loop.
  // Applies node decorations and syncs stop-button disabled state.
  // Replaces the old poll() callback that did this inline.
  useEffect(() => {
    if (!executionLogs || !logsMatchCurrentRun) { return; }
    const { job_stats } = executionLogs;
    applyNodeDecorations(job_stats);

    if (STOP_DISABLED_STATUSES.has(job_stats.status)) {
      setIsStopDisabled(true);
    } else if (job_stats.status === JOB_RUN_STATUS.RUNNING || COMPLETED_STATUSES.has(job_stats.status)) {
      setIsStopDisabled(false);
    }
  }, [executionLogs, logsMatchCurrentRun, applyNodeDecorations]);

  // Open the logs panel automatically once actual log content arrives for this run.
  // node_sequence can be populated before any log text is written, so we check that
  // at least one node has non-empty log content rather than just a non-empty sequence.
  useEffect(() => {
    if (!executionLogs || !logsMatchCurrentRun) { return; }
    const { node_sequence } = executionLogs;
    if (!node_sequence?.length) { return; }
    const hasLogContent = node_sequence.some(
      (nodeId) => !!(executionLogs as Record<string, unknown>)[nodeId]
    );
    if (hasLogContent) {
      setLogsPanelVisible(true);
    }
  }, [executionLogs, logsMatchCurrentRun]);

  // Auto-select the most-recently-active node after each poll:
  // walk backwards through node_sequence and pick the last node that has a node_stats entry.
  // Only fires when the user has not manually selected a node (selectedNodeId is null).
  useEffect(() => {
    // Guard: only act on logs that belong to this run
    if (!executionLogs || !logsMatchCurrentRun || selectedNodeId !== null) {
      return;
    }
    const { node_sequence, job_stats } = executionLogs;
    if (!node_sequence?.length) { return; }

    // Walk backwards to find the deepest node that has stats (= most recently active)
    let autoNode: string | null = null;
    for (let i = node_sequence.length - 1; i >= 0; i--) {
      const nid = node_sequence[i];
      if (nid && job_stats?.node_stats[nid]) {
        autoNode = nid;
        break;
      }
    }
    if (autoNode) {
      setSelectedNodeId(autoNode);
    }
  }, [executionLogs, logsMatchCurrentRun, selectedNodeId]);

  // Handlers — poll lifecycle delegated to Canvas via onStop / onRunAgain props.
  const handleStop = useCallback(() => {
    setIsStopDisabled(true);
    onStop(); // Canvas: cancelJobRun + restart poll to pick up Cancelled status
  }, [onStop]);

  const handleRunAgain = useCallback(() => {
    pendingDecorationsRef.current = null;
    setIsStopDisabled(true);
    setSelectedNodeId(null);
    setLogsPanelVisible(false);
    clearNodeDecorations();
    // Clear stale logs immediately — before the async createJobRun call — so the
    // decoration effect and side panel guard (logsMatchCurrentRun) both see null
    // from the very first render of the new run, not after the API round-trip.
    dispatch(setExecutionLogs(null));
    // Create the new job run directly (no save/validate step).
    void createJobRun({
      entity: {
        job: { asset_ref: jobId, asset_ref_type: JOB_ASSET_REF_TYPE },
        job_run: { configuration: {} },
      },
    }).then((res) => {
      onRunAgain(res.data.job_run_id);
    }).catch(() => {
      // Re-enable Run Again if the create call fails so the user can retry.
      setIsStopDisabled(false);
    });
  }, [jobId, dispatch, onRunAgain, clearNodeDecorations]);

  // Single-click on a node:
  //   • Different node  → open panel, keep current tab, show that node's data
  //   • Same node again → toggle between Log Details (0) and Node Summary (1)
  const handleNodeClick = useCallback((source: { id?: string }) => {
    if (!source.id) { return; }
    const nodeId = String(source.id);
    if (nodeId === selectedNodeId && logsPanelVisible) {
      // Toggle between the two tabs
      setActiveTabIndex((prev) => (prev === 0 ? 1 : 0));
    } else {
      setSelectedNodeId(nodeId);
      setLogsPanelVisible(true);
      // Switch to Node Summary tab (index 1) so stats are immediately visible
      setActiveTabIndex(1);
    }
  }, [selectedNodeId, logsPanelVisible]);

  // Context toolbar on node hover — shows "Node Summary" action.
  // Returns [] for all non-node types so the toolbar stays clean everywhere else.
  const handleContextMenu = useCallback((source: { type?: string }) => {
    if (source.type === 'node') {
      return [
        {
          action: CANVAS_ACTIONS.TOGGLE_RIGHT_PANEL,
          label: intl.formatMessage(messages.nodeSummary),
          enable: true,
          toolbarItem: true,
          icon: <OpenPanelFilledRight size={32} />,
        },
      ];
    }
    return [];
  }, [intl]);

  const handleEditAction = useCallback((data: { editType?: string; [key: string]: unknown }) => {
    if (data.editType === CANVAS_ACTIONS.TOGGLE_RIGHT_PANEL) {
      const nodeId = (data as { editType: string; id?: string }).id;
      if (nodeId && nodeId !== selectedNodeId) {
        // Context toolbar icon clicked on a DIFFERENT node — open panel and show that node
        setSelectedNodeId(nodeId);
        setLogsPanelVisible(true);
        // Keep whatever tab is currently active
      } else if (nodeId && nodeId === selectedNodeId) {
        // Context toolbar icon clicked on the SAME node — toggle between tabs
        setActiveTabIndex((prev) => (prev === 0 ? 1 : 0));
      } else {
        // Toolbar "Open/Close logs" button clicked (no node context) — toggle panel
        setLogsPanelVisible((prev) => !prev);
      }
    }
  }, [selectedNodeId]);

  const handleClickAction = useCallback((rawSource: unknown) => {
    const source = rawSource as { clickType?: string; objectType?: string; id?: string };
    if (source.clickType === 'SINGLE_CLICK' && source.objectType === 'node' && source.id) {
      handleNodeClick(source);
    }
  }, [handleNodeClick]);

  // Canvas configuration (read-only mode).
  // Must be memoized — a new object reference on every re-render propagates into
  // ElyraCanvas's mergedConfig useMemo, which causes CommonCanvas to receive a
  // new config prop and re-initialise (visible as a canvas reload).
  const readOnlyCanvasConfig: CanvasConfig = useMemo(() => ({
    enableInternalObjectModel: true,
    enablePaletteLayout: 'None',
    enableNodeFormatType: 'Horizontal' as const,
    enableToolbarLayout: 'Top',
    enableSnapToGridType: 'After',
    paletteInitialState: false,
    enableLinkType: 'Curve',
    enableLinkDirection: 'LeftRight',
    enableLinkReplaceOnNewConnection: true,
    enableDropZoneOnExternalDrag: false,
    // Enable the context toolbar on node hover — shows the "Node Summary" action
    // via contextMenuHandler returning [{ action: RIGHT_PANEL, label: 'Node Summary' }] for node type.
    enableContextToolbar: true,
    enableHighlightNodeOnNewLinkDrag: true,
    enableSaveZoom: 'None',
    enableEditingActions: false,
    enableMarkdownInComments: false,
    // dataLinkArrowHead exists at runtime but is absent from the bundled .d.ts
    enableCanvasLayout: { dataLinkArrowHead: true } as CanvasConfig['enableCanvasLayout'],
    enableNodeLayout: {
      outputPortDisplay: false,
    },
  }), []); // no deps — this config never changes for the read-only view

  // Toolbar configuration — memoized so ElyraCanvas doesn't re-initialise on every
  // poll-result re-render. Only logsPanelVisible and onExit affect the output.
  const toolbarConfig = useMemo(() => ({
    leftBar: [
      {
        action: CANVAS_ACTIONS.BACK_BUTTON,
        jsx: (
          <div className={styles.toolbarBackButtonParent}>
            <div className={styles.toolbarBackButtonChildDiv} onClick={onExit}>
              <ArrowLeft size={20} />
              <span className={styles.toolbarBackButtonChildSpan}>{intl.formatMessage(messages.back)}</span>
            </div>
          </div>
        ),
      },
      {
        action: CANVAS_ACTIONS.READ_ONLY_TAG,
        jsx: (
          <div className={styles.toolbarReadonlyParent}>
            <div className={styles.toolbarReadonlyChildDiv}>
              <EditOff />
              <span className={styles.toolbarBackButtonChildSpan}>{intl.formatMessage(messages.readOnlyMode)}</span>
            </div>
          </div>
        ),
      },
    ],
    rightBar: [
      { divider: true },
      {
        action: CANVAS_ACTIONS.ZOOM_IN,
        label: intl.formatMessage(messages.zoomIn),
        enable: true,
      },
      {
        action: CANVAS_ACTIONS.ZOOM_OUT,
        label: intl.formatMessage(messages.zoomOut),
        enable: true,
      },
      {
        action: CANVAS_ACTIONS.ZOOM_TO_FIT,
        label: intl.formatMessage(messages.zoomToFit),
        enable: true,
      },
      {
        action: CANVAS_ACTIONS.TOGGLE_RIGHT_PANEL,
        label: intl.formatMessage(logsPanelVisible ? messages.closeLogs : messages.openLogs),
        enable: true,
        iconEnabled: logsPanelVisible ? (
          <RightPanelCloseFilled size={32} />
        ) : (
          <OpenPanelFilledRight size={32} />
        ),
      },
      { divider: true },
    ],
    overrideAutoEnableDisable: true,
  }), [logsPanelVisible, onExit, intl]);

  return (
    <div className={styles.readOnlyCanvasContainer}>
      {/* Canvas fills the full container */}
      <div className={styles.canvasWrapper}>
        <ElyraCanvas
          pipelineFlow={pipelineFlow}
          canvasConfig={readOnlyCanvasConfig}
          toolbarConfig={toolbarConfig}
          editActionHandler={handleEditAction}
          clickActionHandler={handleClickAction}
          contextMenuHandler={handleContextMenu}
          onCanvasControllerReady={handleCanvasControllerReady}
          showTopPanel
          topPanelContent={
            <RunStatusTopPanel
              jobStats={displayJobStats}
              isMinimized={isMinimized}
              isRunning={isRunning}
              isStopDisabled={isStopDisabled}
              onToggleMinimize={() => { setIsMinimized((v) => !v); }}
              onClose={onExit}
              onStop={handleStop}
              onRunAgain={handleRunAgain}
            />
          }
        />
      </div>

      {/* Right logs panel — only render when logs belong to THIS run */}
      {logsPanelVisible && executionLogs && logsMatchCurrentRun && (
        <div className={styles.rightLogsPanelContainer}>
          <RunSidePanel
            executionLogs={executionLogs}
            selectedNodeId={selectedNodeId}
            activeTabIndex={activeTabIndex}
            onTabChange={setActiveTabIndex}
            onClose={() => { setLogsPanelVisible(false); }}
          />
        </div>
      )}
    </div>
  );
}
