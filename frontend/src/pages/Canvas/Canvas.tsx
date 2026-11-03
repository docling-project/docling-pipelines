/* eslint-disable @typescript-eslint/no-unsafe-assignment */
/* eslint-disable @typescript-eslint/no-unsafe-member-access */
/* eslint-disable @typescript-eslint/no-explicit-any */

/* eslint-disable @typescript-eslint/no-unsafe-argument */
/* eslint-disable @typescript-eslint/no-unsafe-call */
import React, { useState, useEffect, useMemo, useCallback, useRef } from 'react';
import type { CanvasConfig, ToolbarConfig } from '@elyra/canvas';
import { IconButton, InlineLoading } from '@carbon/react';
import { type CanvasController, CommonProperties } from '@elyra/canvas';
import type { ClickActionSource } from '@elyra/canvas';
import { useIntl, type MessageDescriptor } from 'react-intl';
import { useDateTimeFormatter } from '@/utils/dateTimeUtils';
import { formatDateTime } from '@/utils/formatters';
import { useParams, useSearchParams, useNavigate } from 'react-router-dom';
import { useDispatch } from 'react-redux';
import type { AppDispatch } from '@/store';
import { ErrorEmptyState } from '@carbon/ibm-products';
import { getProject } from '@/services/api';
import { setProject } from '@/slices/projectsSlice';
import { makeSelectProject } from '@/selectors/projectsSelectors';
import * as projectMapper from '@/services/api/mappers/project-mapper';
import { Save, Play, Edit, TrashCan, Playlist, SettingsAdjust, Information, ArrowLeft, Add } from '@carbon/icons-react';
import { Terminal } from '@carbon/react/icons';
import type { PipelineFlowDef } from '@elyra/canvas';
import type {
  ContextMenuHandler,
  EditActionHandler,
  ClickActionHandler,
} from '@/types/canvas';
import type { Flow, OperatorFeature } from '@/types';
import { hasAnyRequiredParamMissing } from '@/utils/requiredParamValidation';
import type { FlowDefinition } from '@/types/flow';
import type { PaletteData } from '@/types/palette';
import {
  ElyraCanvas,
  Loading,
  ErrorBoundary,
  ReadOnlyCanvas,
} from '@/components';
import { EditDetailsModal, FlowInfoPanel, type FlowPanelData } from '@/components/common';
import {
  FlowRunHistoryTearsheet,
  FlowRunPropertiesTearsheet,
  NodeSuggestion,
  NotificationPanel,
  type NotificationPanelState,
  type NotificationItem,
} from '@/components/Canvas';
import CommonPropertiesPanelWrapper from '@/components/PropertiesPanel/CommonPropertiesPanelWrapper';
import { getParameterDef } from '@/services/parameterDefs';
import { CANVAS_ACTIONS, JOB_ASSET_REF_TYPE } from '@/constants/canvasActions';
import { NodeOperator, BRANCHING_OUTPORT_ID, MERGING_INPORT_ID } from '@/constants/operators';
import { applyAllLinkDecorations } from '@/utils/linkDecorations';
import operatorPaletteData from '@/data/operatorPalette.json';
import { log4js, logUtil } from '@/utils/logger';
import { enhancePalette } from '@/utils/paletteEnhancer';
import { getOperatorMetadata as fetchOperatorMetadata, validateFlow } from '@/services/api';
import { fetchNodeFeatures } from '@/utils/fetchNodeFeatures';
import type { FlowValidationResponse } from '@/services/api';
import { getOperatorMetadata as selectOperatorMetadata } from '@/slices/operatorsSlice';
import { useBreadcrumbActions } from '@/contexts';
import { fetchFlow, saveFlow, clearFlow, setFlowRunProperties, setCurrentFlow, updateFlow } from '@/slices/flowSlice';
import { patchFlow } from '@/services/api';
import {
  useAppSelector,
  useNotify,
  useNodeSuggestion,
  useJobRunPoller,
  useTheme,
} from '@/hooks';
import { selectCurrentFlow, selectFlowError, selectFlowRunProperties } from '@/selectors';
import { selectCurrentJobRunId, selectCurrentJobId, selectIsRunning } from '@/selectors/jobRunSelectors';
import { createJobRun, cancelJobRun } from '@/services/api/actions/job-run-actions';
import { setCurrentRun, setRunning, setExecutionLogs } from '@/slices/jobRunSlice';
import { LinkConditionTearsheet } from '@/components/ElyraCanvas/LinkConditionTearsheet';
import type { LinkConditionValues } from '@/components/ElyraCanvas/LinkConditionTearsheet';
import type { CriteriaJson } from '@/components/PropertiesPanel/CustomPanels/AnnotationFilter/conditionTypes';
import type { FeatureAttributes } from '@/types';
import { messages } from './Canvas.messages';
import styles from './Canvas.module.scss';

const logger = log4js.getLogger('Canvas');

/** Wraps a Redux dispatch result as a resolved Promise for .then/.finally chaining. */
function asPromise(dispatchResult: unknown): Promise<unknown> {
  return new Promise<unknown>((resolve) => { resolve(dispatchResult); });
}

/**
 * Renders the "Last saved …" timestamp in the canvas toolbar.
 * Rendered inside ElyraCanvas's IntlProvider (toolbar jsx slots are mounted
 * inside CommonCanvas's tree), so useDateTimeFormatter() has intl context.
 */
function LastSavedLabel({ date }: { date: Date | null }): React.JSX.Element {
  const intl = useIntl();
  const { formatDate } = useDateTimeFormatter();
  const formatted = date ? formatDate(date, 'short', 'short') : '';
  return <span className={styles.lastSaved}>{intl.formatMessage(messages.lastSaved, { date: formatted })}</span>;
}

/**
 * Pipeline editor page.
 *
 * - Reads `flow_id` from `/flows/:flow_id/canvas` path param.
 * - Reads `project_id` from `?project_id=…` query param for breadcrumb back-nav.
 * - Fetches the flow from the backend on mount via `fetchFlow` thunk.
 * - Tracks dirty state via `canvasController.canUndo()` on every canvas edit.
 * - Shows an active Save button when dirty; shows "Last saved HH:MM" after success.
 * - Shows an inline spinner in place of the Save icon while the PUT is in-flight.
 * - After save, runs async validation when "Validate flow" is enabled in flow run properties.
 */
export function Canvas(): React.JSX.Element {
  const intl = useIntl();
  const dispatch = useDispatch<AppDispatch>();
  const navigate = useNavigate();
  const { isDarkMode } = useTheme();

  // Route: /flows/:flow_id/canvas
  const { flow_id: flowId } = useParams<{ flow_id: string }>();
  // project_id lives in the query string — Breadcrumb reads it too.
  const [searchParams] = useSearchParams();
  const projectId = searchParams.get('project_id');

  const { setActions } = useBreadcrumbActions();

  // Redux — flow loaded from the backend
  const currentFlow = useAppSelector(selectCurrentFlow);
  const flowError = useAppSelector(selectFlowError);
  const flowRunProperties = useAppSelector(selectFlowRunProperties);

  // project is used to gate the fetch — skip if already in the store.
  const project = useAppSelector(makeSelectProject(projectId));

  // isRunMode: local flag — true while ReadOnlyCanvas is mounted.
  const [isRunMode, setIsRunMode] = useState(false);
  const currentJobRunId = useAppSelector(selectCurrentJobRunId);
  const currentJobId = useAppSelector(selectCurrentJobId);
  // isRunning: true while a poll chain is active — drives the toolbar "View run" label.
  const isRunning = useAppSelector(selectIsRunning);

  // Derive the Elyra PipelineFlowDef from the Redux currentFlow definition
  const pipelineFlow = useMemo<PipelineFlowDef | null>(
    () => (currentFlow?.definition as PipelineFlowDef | undefined) ?? null,
    [currentFlow]
  );

  const panelFlow = useMemo<FlowPanelData | null>(() => {
    if (!currentFlow) { return null; }
    return {
      flow_id:      currentFlow.flow_id ?? '',
      name:         currentFlow.name ?? '',
      description:  currentFlow.description ?? '',
      tags:         currentFlow.tags ?? [],
      created_on:   currentFlow.created_on ? formatDateTime(new Date(currentFlow.created_on)) : '',
      modified_on:  currentFlow.modified_on ? formatDateTime(new Date(currentFlow.modified_on)) : '',
      project_name: project?.name ?? projectId ?? '',
    };
  }, [currentFlow, project, projectId]);

  const [isLoading, setIsLoading] = useState(true);
  const notify = useNotify();
  const [isDirty, setIsDirty] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [isValidating, setIsValidating] = useState(false);
  const [lastSavedAt, setLastSavedAt] = useState<Date | null>(null);
  const [isFlowRunHistoryOpen, setIsFlowRunHistoryOpen] = useState(false);
  const [isFlowRunPropertiesOpen, setIsFlowRunPropertiesOpen] = useState(false);
  const [isAboutPanelOpen, setIsAboutPanelOpen] = useState(false);
  const [isEditOpen, setIsEditOpen] = useState(false);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [selectedOperator, setSelectedOperator] = useState<string | null>(null);
  const [isPanelOpen, setIsPanelOpen] = useState(false);
  const [propertiesInfo, setPropertiesInfo] = useState<Record<string, any> | null>(null);

  // ── Node Suggestion ───────────────────────────────────────────────────────
  const {
    nodeSuggestion,
    openNodeSuggestion,
    handleNodeSuggestionClose,
    handleNodeSuggestionSelect: handleNodeSuggestionSelectFromHook,
  } = useNodeSuggestion();

  const handleNodeSuggestionSelect = useCallback(
    (nodeOp: string) => {
      handleNodeSuggestionSelectFromHook(nodeOp, canvasControllerRef.current);
    },
    [handleNodeSuggestionSelectFromHook]
  );

  // ── Branching link-condition state ────────────────────────────────────────
  /** Whether the LinkConditionTearsheet is visible. */
  const [isLinkConditionOpen, setIsLinkConditionOpen] = useState(false);
  /** The canvas link id currently being edited. */
  const [activeLinkId, setActiveLinkId] = useState<string | null>(null);
  /** Pre-populated values for the tearsheet (link name + condition). */
  const [linkConditionForm, setLinkConditionForm] = useState<LinkConditionValues>({
    linkName: '',
    condition: { criteria_json: { logical_operator: 'AND', criteria_list: [] } },
  });
  /** The id of the Branching/Merging node associated with the active link. */
  const [branchingNodeId, setBranchingNodeId] = useState<string>('');
  /** True when the active link points INTO a Merging node (link-name-only tearsheet). */
  const [isMergingLink, setIsMergingLink] = useState(false);
  /**
   * Input features for the condition builder variable dropdown.
   * Populated from the pipeline flow when the tearsheet opens.
   */
  const [linkInputFeatures, setLinkInputFeatures] = useState<Record<string, FeatureAttributes>>({});
  /** Auto-incrementing counter for default link names (Link_0, Link_1, …). */
  const linkNameCounterRef = useRef(0);
  // Holds the Elyra propertiesController instance, obtained via the controllerHandler callback.
  // Used to call applyPropertiesEditing(false) to auto-save before switching nodes.
  const propertiesControllerRef = useRef<any>(null);
  // Tracks the nodeId whose panel is currently open, so openNodePanel can auto-save before
  // switching to a different node.
  const openPanelNodeIdRef = useRef<string | null>(null);
  // Caches fetched paramDefs by operator name — all nodes of the same operator type share
  // the same static paramDef JSON, so one fetch serves every node of that type.
  const memoizedParamDefs = useRef<Record<string, any>>({});
  const [validationData, setValidationData] = useState<FlowValidationResponse | null>(null);
  const canvasControllerRef = useRef<CanvasController | null>(null);
  // Captures the live canvas state at the moment Run is clicked so ReadOnlyCanvas
  // always shows the nodes the user actually ran — even before the first save
  // has been persisted back to Redux.
  const runPipelineFlowRef = useRef<PipelineFlowDef | null>(null);

  // Notification panel state — driven by NotificationPanel component via onStateChange
  const [showBottomPanel, setShowBottomPanel] = useState(false);
  const [notifications, setNotifications] = useState<NotificationItem[]>([]);
  const [bottomPanelContent, setBottomPanelContent] = useState<React.ReactElement | null>(null);
  const [topNotificationBar, setTopNotificationBar] = useState<React.ReactElement | null>(null);

  const handleNotificationStateChange = useCallback((state: NotificationPanelState): void => {
    setShowBottomPanel(state.showBottomPanel);
    setNotifications(state.notifications);
  }, []);

  // One-shot fetch guards — each becomes true after the first invocation and prevents
  // StrictMode's double-invoke from firing duplicate requests. Refs survive the
  // StrictMode unmount/remount cycle so the second mount always sees current=true.
  const fetchedRef = useRef(false);
  const metadataFetchedRef = useRef(false);
  // Live-value refs — kept in sync every render so callbacks can read current values
  // without being recreated every time these change (avoids stale-closure + toolbar churn).
  const isSavingRef = useRef(false);
  const currentFlowRef = useRef(currentFlow);
  const flowRunPropertiesRef = useRef(flowRunProperties);
  isSavingRef.current = isSaving;
  currentFlowRef.current = currentFlow;
  flowRunPropertiesRef.current = flowRunProperties;

  // ── Background poll loop ──────────────────────────────────────────────────
  // Lives in Canvas (not ReadOnlyCanvas) so polling continues even when the user
  // navigates back to the edit canvas mid-run.  All poll machinery (refs, timers,
  // AbortController, cleanup) is encapsulated in useJobRunPoller.
  const { startPoll, stopPoll } = useJobRunPoller();

  const operatorMetadata = useAppSelector(selectOperatorMetadata);
  const isMetadataLoaded = Object.keys(operatorMetadata).length > 0;

  const palette = useMemo(
    () => enhancePalette(operatorPaletteData as PaletteData),
    []
  );

  // Fetch operator metadata exactly once per mount — skip if already in the store.
  // Empty dep array + ref guard matches the fetchedRef pattern used for fetchFlow:
  // fires once, ref prevents StrictMode's second invocation.
  useEffect(() => {
    if (isMetadataLoaded || metadataFetchedRef.current) { return; }
    metadataFetchedRef.current = true;
    void fetchOperatorMetadata(dispatch);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Clears stale flow + run-viewer state, then fetches the current flow exactly once.
  // Guarded by fetchedRef to prevent StrictMode double-invoke and re-render churn
  // from producing duplicate API calls.
  useEffect(() => {
    if (fetchedRef.current) { return; }
    fetchedRef.current = true;

    // Clear stale flow and run-viewer state from a prior navigation.
    dispatch(clearFlow());
    runPipelineFlowRef.current = null;
    dispatch(setRunning(false));
    dispatch(setCurrentRun(null));
    dispatch(setExecutionLogs(null));

    if (!flowId) {
      setIsLoading(false);
      return;
    }
    setIsLoading(true);
    void asPromise(dispatch(fetchFlow(flowId)))
      .then((action) => {
        const typedAction = action as { type: string; payload?: any };
        if (typedAction.type === fetchFlow.fulfilled.type && typedAction.payload) {
          const flow = typedAction.payload as Flow;
          const globalConfig = (flow.definition?.pipelines as any[])?.[0]
            ?.app_data?.ds_flow?.global_config as Record<string, unknown> | undefined;
          if (globalConfig) {
            dispatch(setFlowRunProperties({
              enableIncrementalProcessing:      !globalConfig.force_ingest,
              retainRecordsForDeletedDocuments: Boolean(globalConfig.retain_deleted_docs),
              validateFlow:                     globalConfig.disable_validation !== true,
              enableNodeOutputPreview:          Boolean(globalConfig.enable_peekIn),
              intermediateDataStorage:
                (globalConfig.data_storage_type as 'container' | 'memory' | undefined) ?? 'container',
            }));
          }
        }
      })
      .finally(() => { setIsLoading(false); });
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Fetch the project on hard reload — when navigating directly to /flows/:id/canvas
  // the projects list page has never been visited so state.projects.items is empty.
  useEffect(() => {
    if (!projectId || project) { return; }
    let cancelled = false;
    void getProject(projectId).then((response) => {
      if (cancelled) { return; }
      dispatch(setProject({
        projectId: response.data.project_id,
        project: projectMapper.fromResponse(response.data),
      }));
    });
    return () => { cancelled = true; };
  }, [dispatch, projectId, project]);

  // Inject icon buttons into the breadcrumb bar.
  // Hidden when ReadOnlyCanvas is active (isRunMode) — those actions are irrelevant during a run.
  // Cleared entirely on unmount.
  useEffect(() => {
    setActions(
      isRunMode ? null : (
        <>
          <IconButton
            kind="ghost"
            size="sm"
            label={intl.formatMessage(messages.flowRunHistory)}
            align="bottom-end"
            onClick={() => { setIsFlowRunHistoryOpen(true); }}
          >
            <Playlist size={16} />
          </IconButton>
          <IconButton
            kind="ghost"
            size="sm"
            label={intl.formatMessage(messages.aboutFlow)}
            align="bottom-end"
            onClick={() => { setIsAboutPanelOpen((prev) => !prev); }}
          >
            <Information size={16} />
          </IconButton>
        </>
      )
    );
    return () => { setActions(null); };
  }, [isRunMode, setActions, setIsFlowRunHistoryOpen, setIsAboutPanelOpen, intl]);

  const handleSave = useCallback((): void => {
    // Read live values from refs — avoids stale closure and prevents toolbar churn
    // caused by recreating this callback whenever currentFlow changes after save.
    const flow = currentFlowRef.current;
    if (!flow || isSavingRef.current) { return; }

    const controller = canvasControllerRef.current;
    const latestDefinition = controller
      ? (controller.getPipelineFlow() as unknown as FlowDefinition)
      : flow.definition;

    const flowToSave: Flow = { ...flow, definition: latestDefinition };

    logUtil.info({ logger, message: 'Saving flow', data: { flowId: flow.flow_id } });
    setIsSaving(true);

    void asPromise(dispatch(saveFlow(flowToSave)))
      .then((action) => {
        const typedAction = action as { type: string };
        if (typedAction.type === saveFlow.fulfilled.type) {
          setIsDirty(false);
          setLastSavedAt(new Date());
          notify.success(intl.formatMessage(messages.saveSuccess));

          if (flowRunPropertiesRef.current.validateFlow) {
            // Post-save validation — runs when "Validate flow" is enabled
            setIsValidating(true);
            validateFlow(latestDefinition as object, true)
              .then((res) => {
                setValidationData(res.data);
                logUtil.info({
                  logger,
                  message: 'Post-save validation completed',
                  data: { status: res.data.status },
                });
              })
              .catch((err) => {
                logUtil.warn({ logger, message: 'Post-save validation request failed', data: err });
              })
              .finally(() => {
                setIsValidating(false);
              });
          } else {
            // Validation is disabled — clear any stale notification panel state
            // by injecting a synthetic "succeeded" response. The hook's existing
            // success-clearing logic will dismiss the top bar and close the panel.
            setValidationData({ status: 'succeeded', message: null, errors: [], warnings: [] });
          }
        } else {
          notify.error(intl.formatMessage(messages.saveError));
        }
      })
      .finally(() => {
        setIsSaving(false);
      });
  }, [dispatch, notify, intl]);

  /**
   * Persists flow run properties into the pipeline definition's global_config and
   * saves the flow to the server. Called by FlowRunPropertiesTearsheet on Save.
   *
   * Property → global_config mapping:
   *   enableIncrementalProcessing → force_ingest (inverted: true → force_ingest:false)
   *   retainRecordsForDeletedDocuments → retain_deleted_docs
   *   validateFlow → disable_validation (inverted: true → disable_validation:false)
   *   enableNodeOutputPreview → enable_peekIn
   *   intermediateDataStorage → data_storage_type
   *
   * Called by FlowRunPropertiesTearsheet after it has already dispatched
   * setFlowRunProperties(localProperties) to Redux.
   * The tearsheet passes localProperties as argument so we don't rely on the
   * Redux selector having re-rendered yet (avoids stale-closure race).
   */
  const handleSaveFlowRunProperties = useCallback((savedProperties: {
    enableIncrementalProcessing: boolean;
    retainRecordsForDeletedDocuments: boolean;
    validateFlow: boolean;
    enableNodeOutputPreview: boolean;
    intermediateDataStorage: 'container' | 'memory';
  }): void => {
    const flow = currentFlowRef.current;
    if (!flow) {
      logUtil.warn({ logger, message: 'handleSaveFlowRunProperties called with no flow loaded' });
      return;
    }
    const controller = canvasControllerRef.current;
    const latestDefinition = controller
      ? (controller.getPipelineFlow() as unknown as FlowDefinition)
      : flow.definition;

    // Deep-clone so we don't mutate the Elyra internal object
    const updatedDefinition = structuredClone(latestDefinition) as FlowDefinition;
    const pipelines = updatedDefinition.pipelines as any[] | undefined;
    if (pipelines?.[0]) {
      const pipeline0 = pipelines[0] as Record<string, any>;
      const dsFlow = (pipeline0.app_data?.ds_flow ?? {}) as Record<string, unknown>;
      const existingGlobalConfig = (dsFlow.global_config ?? {}) as Record<string, unknown>;
      dsFlow.global_config = {
        ...existingGlobalConfig,
        force_ingest:        !savedProperties.enableIncrementalProcessing,
        retain_deleted_docs: savedProperties.retainRecordsForDeletedDocuments,
        disable_validation:  !savedProperties.validateFlow,
        enable_peekIn:       savedProperties.enableNodeOutputPreview,
        data_storage_type:   savedProperties.intermediateDataStorage,
      };
      pipeline0.app_data = { ...pipeline0.app_data, ds_flow: dsFlow };
    }

    const flowToSave: Flow = { ...flow, definition: updatedDefinition };

    logUtil.info({
      logger,
      message: 'Saving flow run properties',
      data: { flowId: flow.flow_id, properties: savedProperties },
    });

    setIsSaving(true);
    void dispatch(saveFlow(flowToSave))
      .then((action) => {
        if (saveFlow.fulfilled.match(action)) {
          setIsDirty(false);
          setLastSavedAt(new Date());
          // If the user just disabled validation, clear any stale notification bar
          // left over from a previous failed validation run.
          if (!savedProperties.validateFlow) {
            setValidationData({ status: 'succeeded', message: null, errors: [], warnings: [] });
          }
        }
      })
      .finally(() => {
        setIsSaving(false);
      });
  }, [dispatch]);

  // ── Branching helper functions ──────────────────────────────────────────────

  /**
   * Returns the next auto-generated link name (Link_0, Link_1, …).
   * Increments the counter each time it is called.
   */
  const getNextLinkName = (): string => {
    const name = `Link_${linkNameCounterRef.current}`;
    linkNameCounterRef.current += 1;
    return name;
  };

  /**
   * Returns a unique node label for a newly-created node.
   * If the base label already exists on another node, appends _1, _2, …
   */
  const getUniqueNodeLabel = (baseLabel: string, newNodeId?: string): string => {
    const controller = canvasControllerRef.current;
    if (!controller) { return baseLabel; }
    type FlowNode = Record<string, unknown>;
    const flow = controller.getPipelineFlow() as unknown as { pipelines?: Array<{ nodes?: FlowNode[] }> };
    const allNodes: FlowNode[] = flow?.pipelines?.flatMap((p) => p.nodes ?? []) ?? [];
    const others = allNodes.filter((n) => n['id'] !== newNodeId);
    let label = baseLabel;
    let counter = 1;
    while (others.some(
      (n) => {
        const uiData = ((n['app_data'] as Record<string, unknown> | undefined)?.['ui_data']) as Record<string, unknown> | undefined;
        return (uiData?.['label'] as string | undefined)?.trim()?.toLowerCase() === label.trim().toLowerCase();
      }
    )) {
      label = `${baseLabel}_${counter}`;
      counter += 1;
    }
    return label;
  };

  /**
   * Re-applies link name/condition decorations to every Branching and Merging link.
   * Delegates to the shared `applyAllLinkDecorations` utility (edit mode = not read-only).
   */
  const reapplyAllLinkDecorations = useCallback((): void => {
    const controller = canvasControllerRef.current;
    if (!controller) { return; }
    applyAllLinkDecorations(controller, false);
  // applyAllLinkDecorations and canvasControllerRef are both stable. Empty deps intentional.
  }, []);

  /**
   * Saves a link name + optional condition into the pipeline flow JSON, then re-applies
   * decorations and marks the canvas dirty.
   */
  const persistLinkCondition = (
    linkId: string,
    linkName: string,
    condition: LinkConditionValues['condition'],
    isMerge: boolean,
    mergingNodeId?: string
  ): void => {
    const controller = canvasControllerRef.current;
    if (!controller || !linkId) { return; }

    type FlowNode = Record<string, unknown>;
    type FlowLink = Record<string, unknown>;
    type FlowInput = { id: string; links?: FlowLink[] };
    const flow = controller.getPipelineFlow() as any;
    const nodes: FlowNode[] = (flow?.pipelines?.[0]?.nodes as FlowNode[] | undefined) ?? [];
    let finalLinkName = linkName.trim();
    if (!finalLinkName) { finalLinkName = getNextLinkName(); }

    if (isMerge && mergingNodeId) {
      const mergingNode = nodes.find((n) => n['id'] === mergingNodeId && n['op'] === NodeOperator.MERGING);
      if (!mergingNode) { return; }
      const mergeInputs = (mergingNode['inputs'] as FlowInput[] | undefined) ?? [];
      mergeInputs.forEach((input) => {
        (input.links ?? []).forEach((link) => {
          if (link['id'] === linkId) { Object.assign(link, { link_name: finalLinkName }); }
        });
      });
      setBranchingNodeId(mergingNodeId);
    } else {
      let srcNodeId = '';
      let targetNodeId = '';
      let targetPortId = '';
      nodes.forEach((targetNode) => {
        const targetInputs = (targetNode['inputs'] as FlowInput[] | undefined) ?? [];
        targetInputs.forEach((input) => {
          (input.links ?? []).forEach((link) => {
            if (link['id'] === linkId) {
              srcNodeId    = link['node_id_ref'] as string;
              targetNodeId = targetNode['id']    as string;
              targetPortId = input.id;
            }
          });
        });
      });
      if (!srcNodeId) { return; }
      const branchingNode = nodes.find((n) => n['id'] === srcNodeId && n['op'] === NodeOperator.BRANCHING);
      if (!branchingNode) { return; }
      const existingParams   = (branchingNode['parameters'] as Record<string, unknown> | undefined) ?? {};
      const existing: FlowLink[] = (existingParams['link_conditions'] as FlowLink[] | undefined) ?? [];
      Object.assign(branchingNode, {
        parameters: {
          ...existingParams,
          link_conditions: [
            ...existing.filter((lc) => lc['link_id'] !== linkId),
            {
              link_id: linkId,
              target_node_id: targetNodeId,
              target_port_id: targetPortId,
              link_name: finalLinkName,
              condition: condition ?? { criteria_json: { logical_operator: 'AND', criteria_list: [] } },
            },
          ],
        },
      });
      setBranchingNodeId(srcNodeId);
    }

    controller.setPipelineFlow({ ...flow });
    reapplyAllLinkDecorations();
    setIsDirty(true);
  };

  /** Strips the condition (name + criteria) from a link without deleting the link. */
  const removeConditionFromLink = (linkId: string): void => {
    const controller = canvasControllerRef.current;
    if (!controller) { return; }
    type FlowNode = Record<string, unknown>;
    type FlowLink = Record<string, unknown>;
    const flow = controller.getPipelineFlow() as any;
    const nodes: FlowNode[] = (flow?.pipelines?.[0]?.nodes as FlowNode[] | undefined) ?? [];
    nodes.forEach((node) => {
      if (node['op'] === NodeOperator.BRANCHING) {
        const params   = (node['parameters'] as Record<string, unknown> | undefined) ?? {};
        const existing: FlowLink[] = (params['link_conditions'] as FlowLink[] | undefined) ?? [];
        Object.assign(node, {
          parameters: {
            ...params,
            link_conditions: existing.map((lc) =>
              lc['link_id'] === linkId
                ? { link_id: lc['link_id'], target_node_id: lc['target_node_id'], target_port_id: lc['target_port_id'] }
                : lc
            ),
          },
        });
      }
    });

    controller.setPipelineFlow({ ...flow });
    reapplyAllLinkDecorations();
    setIsDirty(true);
  };

  /** Removes link_conditions entries whose link_id is gone from the canvas (after delete/undo). */
  const syncDeletedLinks = (): void => {
    const controller = canvasControllerRef.current;
    if (!controller) { return; }
    type FlowNode = Record<string, unknown>;
    type FlowLink = Record<string, unknown>;
    const activeLinkSet = new Set(
      (controller.getLinks() as Array<{ id: string }>).map((l) => l.id)
    );
    const flow = controller.getPipelineFlow() as any;
    const nodes: FlowNode[] = (flow?.pipelines?.[0]?.nodes as FlowNode[] | undefined) ?? [];
    let changed = false;
    nodes.forEach((node) => {
      if (node['op'] === NodeOperator.BRANCHING) {
        const params   = (node['parameters'] as Record<string, unknown> | undefined) ?? {};
        const before: FlowLink[]   = (params['link_conditions'] as FlowLink[] | undefined) ?? [];
        const after    = before.filter((lc) => activeLinkSet.has(lc['link_id'] as string));
        if (after.length !== before.length) {
          Object.assign(node, { parameters: { ...params, link_conditions: after } });
          changed = true;
        }
      }
    });
    if (changed) {

      controller.setPipelineFlow({ ...flow });
      reapplyAllLinkDecorations();
    }
  };

  /**
   * Opens the `LinkConditionTearsheet` for the given link id.
   * Reads any existing condition from the pipeline flow to pre-populate the form.
   */
  const openLinkConditionTearsheet = useCallback((linkId: string): void => {
    const controller = canvasControllerRef.current;
    if (!controller) { return; }
    type FlowNode = Record<string, unknown>;
    type FlowLink = Record<string, unknown>;
    type FlowInput = { id: string; links?: FlowLink[] };
    const flow = controller.getPipelineFlow() as any;
    const nodes: FlowNode[] = (flow?.pipelines?.[0]?.nodes as FlowNode[] | undefined) ?? [];

    // Detect Merging link
    let foundMergingNode: FlowNode | null = null;
    for (const node of nodes) {
      if (node['op'] === NodeOperator.MERGING) {
        const inputs = (node['inputs'] as FlowInput[] | undefined) ?? [];
        for (const input of inputs) {
          if ((input.links ?? []).some((l) => l['id'] === linkId)) {
            foundMergingNode = node;
          }
        }
      }
    }

    if (foundMergingNode) {
      const mergeInputs = (foundMergingNode['inputs'] as FlowInput[] | undefined) ?? [];
      const link = mergeInputs
        .flatMap((inp) => inp.links ?? [])
        .find((l) => l['id'] === linkId);
      setLinkConditionForm({ linkName: (link?.['link_name'] as string | undefined) ?? '' });
      setBranchingNodeId(foundMergingNode['id'] as string);
      setIsMergingLink(true);
      setLinkInputFeatures({});
    } else {
      // Branching link
      let foundCondition: FlowLink | null = null;
      let srcBranchingNodeId = '';
      nodes.forEach((n) => {
        if (n['op'] === NodeOperator.BRANCHING) {
          const params = (n['parameters'] as Record<string, unknown> | undefined) ?? {};
          const lc = (params['link_conditions'] as FlowLink[] | undefined)?.find((c) => c['link_id'] === linkId);
          if (lc) { foundCondition = lc; srcBranchingNodeId = n['id'] as string; }
        }
      });
      setBranchingNodeId(srcBranchingNodeId);
      setIsMergingLink(false);
      setLinkInputFeatures({});

      // Async-load features for the condition builder variable dropdown
      void fetchNodeFeatures(flow as unknown as PipelineFlowDef).then((featureMap) => {
        const f = featureMap[srcBranchingNodeId];
        if (f?.input_features) { setLinkInputFeatures(f.input_features); }
      }).catch(() => { /* best-effort */ });

      const fc = foundCondition as Record<string, unknown> | null;
      const fcCond = fc?.['condition'] as Record<string, unknown> | undefined;
      const fcCriteriaJson = fcCond?.['criteria_json'] as Record<string, unknown> | undefined;
      if (fcCriteriaJson) {
        setLinkConditionForm({
          linkName: (fc?.['link_name'] as string | undefined) ?? '',
          condition: {
            criteria_json: {
              logical_operator: (fcCriteriaJson['logical_operator'] as string | undefined) ?? 'AND',
              criteria_list: (fcCriteriaJson['criteria_list'] as CriteriaJson['criteria_list']) ?? [],
            },
          },
        });
      } else if (fcCond?.['criteria_list']) {
        setLinkConditionForm({
          linkName: (fc?.['link_name'] as string | undefined) ?? '',
          condition: { criteria_list: fcCond['criteria_list'] as string[] },
        });
      } else {
        setLinkConditionForm({
          linkName: (fc?.['link_name'] as string | undefined) ?? '',
          condition: { criteria_json: { logical_operator: 'AND', criteria_list: [] } },
        });
      }
    }

    setActiveLinkId(linkId);
    setIsLinkConditionOpen(true);
  }, []);

  /** Called by `LinkConditionTearsheet` when the user clicks Save. */
  const handleSaveLinkCondition = (
    linkName: string,
    condition: LinkConditionValues['condition'],
    mergingNodeId?: string
  ): void => {
    if (activeLinkId) {
      persistLinkCondition(activeLinkId, linkName, condition, isMergingLink, mergingNodeId);
    }
    setIsLinkConditionOpen(false);
    setActiveLinkId(null);
    setIsMergingLink(false);
  };

  const handleRun = useCallback((): void => {
    // If a run is already in-progress, re-enter the viewer instead of starting a new one.
    if (isRunning && currentJobRunId) {
      setIsRunMode(true);
      return;
    }

    const flow = currentFlowRef.current;
    if (!flow?.flow_id) {
      logUtil.error({ logger, message: 'Cannot run: no flow_id' });
      return;
    }

    void (async () => {
      const controller = canvasControllerRef.current;
      const latestDefinition = controller
        ? (controller.getPipelineFlow() as unknown as FlowDefinition)
        : flow.definition;

      // Capture live canvas state NOW — before any async step — so ReadOnlyCanvas
      // always shows exactly what was submitted, not the potentially-stale Redux copy.
      runPipelineFlowRef.current = latestDefinition as unknown as PipelineFlowDef;

      // ── Step 1: Save if dirty ────────────────────────────────────────────────
      if (isDirty) {
        setIsSaving(true);
        const flowToSave: Flow = { ...flow, definition: latestDefinition };
        const action = await asPromise(dispatch(saveFlow(flowToSave))) as { type: string };
        setIsSaving(false);
        if (action.type !== saveFlow.fulfilled.type) {
          logUtil.error({ logger, message: 'Run aborted: save failed before run' });
          return;
        }
        setIsDirty(false);
        setLastSavedAt(new Date());
      }

      // ── Step 2: Validate (if enabled in Flow Run Properties) ─────────────────
      if (flowRunPropertiesRef.current.validateFlow) {
        setIsValidating(true);
        try {
          const res = await validateFlow(latestDefinition as object, true);
          setValidationData(res.data);
          if (res.data.status?.toLowerCase() === 'failed') {
            logUtil.warn({ logger, message: 'Run aborted: validation failed', data: res.data });
            return;
          }
        } catch (err) {
          logUtil.warn({ logger, message: 'Validation request failed, proceeding with run', data: err });
        } finally {
          setIsValidating(false);
        }
      } else {
        // Validation disabled — clear any stale top-bar left over from a previous
        // run where validation was on and had failures.
        setValidationData({ status: 'succeeded', message: null, errors: [], warnings: [] });
      }

      // ── Step 3: Create job run ────────────────────────────────────────────────
      const flowId = flow.flow_id!;
      try {
        const res = await createJobRun({
          entity: {
            job: { asset_ref: flowId, asset_ref_type: JOB_ASSET_REF_TYPE, name: flow.name ?? flowId },
            job_run: { configuration: {} },
          },
        });
        const newJobRunId = res.data.job_run_id;
        // Clear stale logs before setting new IDs so ReadOnlyCanvas never mounts
        // with a mismatched (jobRunId prop ≠ executionLogs.job_stats.job_run_id).
        dispatch(setExecutionLogs(null));
        dispatch(setCurrentRun({ jobId: flowId, jobRunId: newJobRunId }));
        startPoll(newJobRunId);   // starts poll + dispatches setRunning(true)
        setIsRunMode(true);
      } catch (err: unknown) {
        dispatch(setRunning(false));
        logUtil.error({ logger, message: 'Failed to start job run', data: err });
        notify.error(intl.formatMessage(messages.runStartError));
      }
    })();
  }, [isDirty, dispatch, isRunning, currentJobRunId, startPoll, notify, intl]);

  // Canvas configuration
  const canvasConfig: CanvasConfig = useMemo(
    () => ({
      enableInternalObjectModel: true,
      enablePaletteLayout: 'Flyout',
      enableNodeFormatType: 'Horizontal',
      enableToolbarLayout: 'Top',
      enableSnapToGridType: 'After',
      paletteInitialState: true,
      enableLinkType: 'Curve',
      enableLinkDirection: 'LeftRight',
      // 'None' means links are not independently selectable.
      enableLinkSelection: 'None',
      enableLinkReplaceOnNewConnection: true,
      enableDropZoneOnExternalDrag: true,
      enableContextToolbar: true,
      enableHighlightNodeOnNewLinkDrag: true,
      enableSaveZoom: 'None',
      enableEditingActions: true,
      enableMarkdownInComments: false,
      // linkGap + linkContextToolbar positions for the canvas layout.
      // dataLinkArrowHead exists at runtime but is absent from the bundled .d.ts.
      enableCanvasLayout: {
        dataLinkArrowHead: true,
        linkGap: 4,
        linkContextToolbarPosX: 0,
        linkContextToolbarPosY: -8,
      } as CanvasConfig['enableCanvasLayout'],
    }),
    []
  );

  // Toolbar — recomputes when isDirty / isSaving / lastSavedAt change
  // Context menu handler
  const contextMenuHandler: ContextMenuHandler = useCallback(
    (source, defaultMenu): ReturnType<ContextMenuHandler> => {
      if (source.type === 'node') {
        return [
          {
            action: CANVAS_ACTIONS.EDIT_NODE, label: intl.formatMessage(messages.edit),
            enable: true, icon: <Edit size={32} />, toolbarItem: true,
          },
          {
            action: CANVAS_ACTIONS.RECOMMEND_NODES, label: intl.formatMessage(messages.recommendNodes),
            enable: true, icon: <Playlist size={32} />, toolbarItem: true,
          },
          {
            action: CANVAS_ACTIONS.DELETE, label: intl.formatMessage(messages.delete),
            enable: true, icon: <TrashCan size={32} />, toolbarItem: true,
          },
        ];
      }
      if (source.type === 'comment') {
        return [
          {
            action: CANVAS_ACTIONS.EDIT_COMMENT, label: intl.formatMessage(messages.edit),
            enable: true, icon: <Edit size={32} />, toolbarItem: true,
          },
          {
            action: CANVAS_ACTIONS.DELETE, label: intl.formatMessage(messages.delete),
            enable: true, icon: <TrashCan size={32} />, toolbarItem: true,
          },
        ];
      }
      // ── Link context menu ──────────────────────────────────────────────────
      if (source.type === 'link') {
        const linkId = (source as any).id as string;
        const srcPortId = (source.targetObject as any)?.srcNodePortId as string | undefined;
        const trgPortId = (source.targetObject as any)?.trgNodePortId as string | undefined;
        const srcObj = (source.targetObject as any)?.srcObj;

        const isBranchingLink = srcObj?.op === NodeOperator.BRANCHING || srcPortId === BRANCHING_OUTPORT_ID;
        const isMergingLink2 = trgPortId === MERGING_INPORT_ID;

        if (isBranchingLink) {
          const linkConditions: any[] = srcObj?.parameters?.link_conditions ?? [];
          const hasCondition = !!(linkConditions.find((lc: any) => lc.link_id === linkId)?.link_name);
          return [
            {
              action: CANVAS_ACTIONS.DELETE_LINK,
              label: intl.formatMessage(messages.deleteLink),
              enable: true,
              toolbarItem: true,
              icon: <TrashCan size={16} />,
              ...(hasCondition ? {
                submenu: true,
                menu: [
                  { action: CANVAS_ACTIONS.DELETE_LINK, label: intl.formatMessage(messages.deleteLink), enable: true },
                  { action: CANVAS_ACTIONS.DELETE_CONDITION, label: intl.formatMessage(messages.deleteCondition), enable: true },
                ],
              } : {}),
            },
            {
              action: CANVAS_ACTIONS.ADD_CONDITION,
              enable: true,
              toolbarItem: true,
              label: intl.formatMessage(hasCondition ? messages.editCondition : messages.addCondition),
              icon: hasCondition ? <Edit size={16} /> : <Add size={16} />,
            },
          ];
        }
        if (isMergingLink2) {
          return [
            {
              action: CANVAS_ACTIONS.DELETE_LINK, label: intl.formatMessage(messages.deleteLink),
              enable: true, toolbarItem: true, icon: <TrashCan size={16} />,
            },
            {
              action: CANVAS_ACTIONS.ADD_CONDITION, label: intl.formatMessage(messages.editLinkName),
              enable: true, toolbarItem: true, icon: <Edit size={16} />,
            },
          ];
        }
      }
      return defaultMenu;
    },
    [intl]
  );

  /**
   * Writes attribute defaults into a node immediately on drop, so node.parameters
   * is never empty when the flow is saved without opening the panel.
   *
   * Three resolution strategies per attribute, tried in order:
   *   1. Scalar  — attr.default when it is a non-null value (explicit backend default).
   *   2. providers style (e.g. provider_config) — built from the active provider's property defaults.
   *   3. properties style (e.g. output_format, text_extraction) — built from a flat sub-properties map.
   */
  const applyNodeDefaults = useCallback((nodeId: string, nodeOp: string): void => {
    const controller = canvasControllerRef.current;
    if (!controller) { return; }

    // ── Branching / Merging: no operatorMetadata attributes — stamp static defaults ──
    if (nodeOp === NodeOperator.BRANCHING) {
      controller.setNodeParameters(nodeId, { link_conditions: [] } as unknown as Array<Record<string, unknown>>);
      return;
    }
    if (nodeOp === NodeOperator.MERGING) {
      controller.setNodeParameters(nodeId, { merge_type: 'rows', column_option: 'inner_join' } as unknown as Array<Record<string, unknown>>);
      return;
    }

    const attrs = operatorMetadata[nodeOp]?.attributes;
    if (!attrs) { return; }

    // Only present on operators with a provider selector (e.g. vectordb).
    // Empty string is falsy — the providers branch below is skipped for all others.
    const activeProvider = (attrs['provider']?.default as string | undefined) ?? '';

    const defaults = Object.entries(attrs).reduce<Record<string, unknown>>(
      (acc, [paramId, attr]) => {
        let value: unknown = attr.default ?? undefined;

        // providers style (e.g. vectordb/embeddings provider_config)
        if (value === undefined && attr.providers && activeProvider) {
          const providerSchema = attr.providers[activeProvider];
          if (providerSchema?.properties) {
            const built: Record<string, unknown> = {};
            for (const [k, propDef] of Object.entries(providerSchema.properties)) {
              if (propDef.default !== undefined) { built[k] = propDef.default; }
            }
            if (Object.keys(built).length > 0) { value = built; }
          }
        }

        // properties style (e.g. output_format, output_structure, text_extraction)
        if (value === undefined && attr.properties) {
          const built: Record<string, unknown> = {};
          for (const [k, propDef] of Object.entries(attr.properties)) {
            if (propDef.default !== undefined) { built[k] = propDef.default; }
          }
          if (Object.keys(built).length > 0) { value = built; }
        }

        if (value !== undefined) {
          return { ...acc, [paramId]: value };
        }
        return acc;
      },
      {}
    );

    if (Object.keys(defaults).length === 0) { return; }

    controller.setNodeParameters(nodeId, defaults as unknown as Array<Record<string, unknown>>);
    logUtil.info({ logger, message: 'Applied node defaults', data: { nodeId, nodeOp, defaults } });
  }, [operatorMetadata]);

  /** Opens the properties panel for a node. */
  const openNodePanel = useCallback((nodeId: string): void => {
    const controller = canvasControllerRef.current;
    if (!controller) { return; }
    const node = controller.getNode(nodeId);
    if (node?.type !== 'execution_node') { return; }

    // Auto-save the currently open panel before switching nodes.
    if (openPanelNodeIdRef.current && openPanelNodeIdRef.current !== nodeId) {

      propertiesControllerRef.current?.applyPropertiesEditing?.(false);
    }

    const operatorName = node.op;
    setSelectedNodeId(nodeId);
    setSelectedOperator(operatorName);
    openPanelNodeIdRef.current = nodeId;

    const currentPipelineFlow = controller.getPipelineFlow();

    const openWithParamDef = (paramDef: any): void => {
      const paramDefWithValues = { ...paramDef };
      // Only set current_parameters when the node already has saved values.
      // A fresh node has parameters={} so the key-count guard ensures we don't
      // overwrite parameter.default with an empty object.
      if (Object.keys(node.parameters as Record<string, unknown>).length > 0) {
        paramDefWithValues.current_parameters = node.parameters;
      }

      const nodeMessages = controller.getNodeMessages(nodeId) ?? [];

      // Phase 1 — open immediately with featuresLoading:true so the flyout and
      // DataTableSkeleton appear right away while the API call is in-flight.
      setPropertiesInfo({
        parameterDef: paramDefWithValues,
        appData: {
          nodeId,
          operatorMetadata,
          pipelineFlow: currentPipelineFlow,
          canvasController: controller,
          nodeFeatureMap: {},
          featuresLoading: true,
        },
        messages: nodeMessages,
        id: nodeId,
      });
      setIsPanelOpen(true);

      // Phase 2 — update appData only once features arrive.
      // Deliberately does NOT touch parameterDef so Elyra does not re-run
      // setForm or reset the expand button state.
      void fetchNodeFeatures(currentPipelineFlow).catch(() => ({})).then((nodeFeatureMap) => {
        setPropertiesInfo((prev) => {
          if (prev?.id !== nodeId) { return prev; }
          return {
            ...prev,
            appData: { ...prev.appData, nodeFeatureMap, featuresLoading: false },
          };
        });
        logUtil.info({ logger, message: 'Node features loaded', data: { nodeId, operator: operatorName } });
      });
    };

    if (memoizedParamDefs.current[operatorName]) {
      // Already fetched for this operator type — reuse the cached paramDef and
      // update current_parameters from the latest canvas node state.
      const cached = { ...memoizedParamDefs.current[operatorName] };
      if (Object.keys(node.parameters as Record<string, unknown>).length > 0) { cached.current_parameters = node.parameters; }
      openWithParamDef(cached);
      return;
    }

    void getParameterDef({ operatorName }).then((paramDef) => {
      memoizedParamDefs.current[operatorName] = paramDef;
      openWithParamDef(paramDef);
    });
  }, [operatorMetadata]);

  const hasNotifications = notifications.length > 0;
  // Button is enabled only when validation is on AND there are results to show
  const isTerminalEnabled = flowRunProperties.validateFlow && hasNotifications;
  const validationToggleMessage = !flowRunProperties.validateFlow
    ? messages.validationDisabled
    : hasNotifications
      ? messages.validationProblems
      : messages.noValidationProblems;

  // Toolbar — recomputes when relevant state changes
  const toolbarConfig: ToolbarConfig = useMemo(() => {
    const barItem = (action: string, label: MessageDescriptor, tooltip: MessageDescriptor): object => ({
      action,
      label: intl.formatMessage(label),
      enable: true,
      tooltip: intl.formatMessage(tooltip),
    });

    const leftBar: object[] = [
      barItem(CANVAS_ACTIONS.PALETTE, messages.toolbarPalette, messages.toolbarPaletteTooltip),
      { divider: true },
      barItem(CANVAS_ACTIONS.UNDO, messages.toolbarUndo, messages.toolbarUndoTooltip),
      barItem(CANVAS_ACTIONS.REDO, messages.toolbarRedo, messages.toolbarRedoTooltip),
      { divider: true },
      barItem(CANVAS_ACTIONS.CUT, messages.toolbarCut, messages.toolbarCutTooltip),
      barItem(CANVAS_ACTIONS.COPY, messages.toolbarCopy, messages.toolbarCopyTooltip),
      barItem(CANVAS_ACTIONS.PASTE, messages.toolbarPaste, messages.toolbarPasteTooltip),
      barItem(CANVAS_ACTIONS.DELETE, messages.delete, messages.toolbarDeleteTooltip),
      { divider: true },
      barItem(CANVAS_ACTIONS.CREATE_COMMENT, messages.toolbarComment, messages.toolbarCommentTooltip),
      { divider: true },
      {
        action: CANVAS_ACTIONS.FLOW_PROPERTIES,
        label: intl.formatMessage(messages.toolbarFlowRunProperties),
        enable: true,
        tooltip: intl.formatMessage(messages.toolbarFlowRunPropertiesTooltip),
        iconEnabled: <SettingsAdjust size={32} />,
      },
      { divider: true },
      barItem(CANVAS_ACTIONS.ZOOM_IN, messages.toolbarZoomIn, messages.toolbarZoomInTooltip),
      barItem(CANVAS_ACTIONS.ZOOM_OUT, messages.toolbarZoomOut, messages.toolbarZoomOutTooltip),
      barItem(CANVAS_ACTIONS.ZOOM_TO_FIT, messages.toolbarZoomToFit, messages.toolbarZoomToFitTooltip),
    ];

    const rightBar: object[] = [
      // Save/validate status indicator — shown only when relevant
      ...((isSaving || isValidating || lastSavedAt)
        ? [{
            action: 'save-status',
            jsx: (_tabIndex: number) => {
              if (isSaving) {
                return (
                  <div className={styles.saveStatus}>
                    <InlineLoading description={intl.formatMessage(messages.saving)} />
                  </div>
                );
              }
              if (isValidating) {
                return (
                  <div className={styles.saveStatus}>
                    <InlineLoading description={intl.formatMessage(messages.validating)} />
                  </div>
                );
              }
              return <div className={styles.saveStatus}><LastSavedLabel date={lastSavedAt} /></div>;
            },
          }, { divider: true }]
        : []),
      {
        action: CANVAS_ACTIONS.SAVE,
        label: intl.formatMessage(messages.toolbarSave),
        enable: isDirty && !isSaving,
        tooltip: intl.formatMessage(messages.toolbarSaveTooltip),
        iconEnabled: <Save size={32} />,
        kind: 'ghost',
      },
      { divider: true },
      {
        action: CANVAS_ACTIONS.RUN,
        // "View run" while a run is in-progress; reverts to "Run flow" once complete.
        label: intl.formatMessage(isRunning && currentJobRunId ? messages.viewRun : messages.runFlow),
        enable: !isSaving && !isValidating,
        kind: 'primary',
        tooltip: intl.formatMessage(isRunning && currentJobRunId ? messages.viewRunTooltip : messages.runFlowTooltip),
        iconEnabled: <Play size={32} />,
        incLabelWithIcon: 'before',
      },
      {
        action: 'toggle-bottom-panel',
        jsx: () => (
          <button
            type="button"
            className={`${styles.panelToggleButton} ${showBottomPanel ? styles.panelToggleButtonActive : ''}`}
            disabled={!isTerminalEnabled}
            title={intl.formatMessage(validationToggleMessage)}
            aria-label={intl.formatMessage(validationToggleMessage)}
            onClick={() => {
              if (!isTerminalEnabled) { return; }
              window.dispatchEvent(new CustomEvent(showBottomPanel ? 'hideBottomPanel' : 'showBottomPanel'));
            }}
          >
            <Terminal size={16} />
          </button>
        ),
      },
    ];

    return { leftBar, rightBar, overrideAutoEnableDisable: true };

  }, [isDirty, isSaving, isValidating, lastSavedAt, showBottomPanel, isTerminalEnabled, isRunning, currentJobRunId, intl, validationToggleMessage]);

  // Edit action handler — also tracks dirty state via canUndo()
  const editActionHandler: EditActionHandler = useCallback(
    (data) => {
      if (data.editType === CANVAS_ACTIONS.SAVE)            { handleSave(); return; }
      if (data.editType === CANVAS_ACTIONS.RUN)             { handleRun();  return; }
      if (data.editType === CANVAS_ACTIONS.FLOW_PROPERTIES) { setIsFlowRunPropertiesOpen(true); return; }
      if (data.editType === 'flow-run-history')             { setIsFlowRunHistoryOpen(true); return; }

      if (data.editType === CANVAS_ACTIONS.EDIT_NODE && data.targetObject) {
        openNodePanel((data.targetObject as { id: string }).id);
        return;
      }

      // ── Recommend nodes — open NodeSuggestion card from toolbar button ───────
      if (data.editType === CANVAS_ACTIONS.RECOMMEND_NODES && data.targetObject) {
        const nodeId = (data.targetObject as { id: string }).id;
        const controller = canvasControllerRef.current;
        if (nodeId && controller) {
          openNodeSuggestion(nodeId, controller);
        }
        return;
      }

      // ── Branching link condition actions ────────────────────────────────────
      if (data.type === 'link' && data.editType === CANVAS_ACTIONS.ADD_CONDITION) {
        openLinkConditionTearsheet((data as any).id as string);
        return;
      }
      if (data.type === 'link' && data.editType === CANVAS_ACTIONS.EDIT_CONDITION) {
        openLinkConditionTearsheet((data as any).id as string);
        return;
      }
      if (data.type === 'link' && data.editType === CANVAS_ACTIONS.DELETE_CONDITION) {
        removeConditionFromLink((data as any).id as string);
        return;
      }

      if (data.editType === CANVAS_ACTIONS.CREATE_NODE ||
          data.editType === CANVAS_ACTIONS.CREATE_AUTO_NODE) {
        // Palette drag fires 'createAutoNode'; programmatic creation fires 'createNode'.
        // Both stamp data.newNode after the command executes — apply defaults immediately.
        const d = data as any;
        const { newNode } = d as { newNode?: { id: string; op: string; label?: string } };
        if (newNode?.id && newNode?.op) {
          applyNodeDefaults(newNode.id, newNode.op);
          // Open panel immediately for operators with required parameters that have no default
          if (newNode.op === NodeOperator.DOCUMENT_SET) {
            openNodePanel(newNode.id);
          }
        }

        // ── Unique node label ─────────────────────────────────────────────────────────
        // When a second Branching/Merging (or any) node is dropped, give it a
        // suffix (_1, _2, …) so labels are unique across the canvas.
        if (newNode?.id && newNode?.label) {
          const uniqueLabel = getUniqueNodeLabel(newNode.label, newNode.id);
          if (uniqueLabel !== newNode.label) {

            canvasControllerRef.current?.setNodeLabel(newNode.id, uniqueLabel, d.pipelineId);
          }
        }

        // ── Auto-name new links from Branching nodes ─────────────────────────
        // When a node is dragged from the palette onto an existing Branching node
        // (createAutoNode path), Elyra auto-creates a link. Stamp it with a default
        // link name and add the pill decoration immediately.
        if (data.editType === CANVAS_ACTIONS.CREATE_AUTO_NODE) {
          const srcNode = d.sourceNode;
          const {newLink} = d;
          const newNodeObj = d.newNode;

          if (newLink?.id && srcNode?.op === NodeOperator.BRANCHING) {
            // New node dropped onto a Branching node output → auto-name the link
            const defaultName = getNextLinkName();
            persistLinkCondition(
              newLink.id as string,
              defaultName,
              { criteria_json: { logical_operator: 'AND', criteria_list: [] } },
              false
            );
          } else if (newLink?.id && newNodeObj?.op === NodeOperator.MERGING) {
            // New node is a Merging node — auto-name the incoming link
            const defaultName = getNextLinkName();
            persistLinkCondition(newLink.id as string, defaultName, undefined, true, newNodeObj.id as string);
          }
        }

        // Fall-through to setIsDirty is intentional — node creation marks the flow dirty.
      }

      // ── linkNodes — when a link is drawn manually between two nodes ─────────
      if (data.editType === 'linkNodes') {
        const d = data as any;
        const sourcePortId = (d.nodes?.[0]?.portId as string | undefined) ?? '';
        const targetPortId = (d.targetNodes?.[0]?.portId as string | undefined) ?? '';
        const linkId = (d.linkIds?.[0] as string | undefined) ?? '';

        if (linkId && sourcePortId === BRANCHING_OUTPORT_ID) {
          const defaultName = getNextLinkName();
          persistLinkCondition(linkId, defaultName, { criteria_json: { logical_operator: 'AND', criteria_list: [] } }, false);
        } else if (linkId && targetPortId === MERGING_INPORT_ID) {
          const defaultName = getNextLinkName();
          persistLinkCondition(linkId, defaultName, undefined, true, d.targetNodes?.[0]?.id as string);
        }
      }

      // ── Clean up stale link_conditions after delete / undo / redo ──────────
      if (
        data.editType === CANVAS_ACTIONS.DELETE ||
        data.editType === CANVAS_ACTIONS.DELETE_LINK ||
        data.editType === CANVAS_ACTIONS.UNDO ||
        data.editType === CANVAS_ACTIONS.REDO ||
        data.editType === CANVAS_ACTIONS.CUT
      ) {
        syncDeletedLinks();
        // Re-apply decorations since undo/redo can restore links
        reapplyAllLinkDecorations();
      }

      // Re-check dirty state after any canvas mutation (add, move, link, delete, undo, redo).
      const controller = canvasControllerRef.current;
      if (controller) { setIsDirty(controller.canUndo()); }
    },
    // openLinkConditionTearsheet is useCallback(fn,[]) — stable.
    // removeConditionFromLink, syncDeletedLinks, persistLinkCondition are plain functions
    // re-created every render; listing them here would cause unnecessary callback churn.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [handleRun, handleSave, openNodePanel, applyNodeDefaults, openLinkConditionTearsheet]
  );

  // Double-click on a node opens the properties panel.
  // Single-click on an output port opens the Node Suggestion panel.
  const clickActionHandler: ClickActionHandler = useCallback((rawSource) => {
    const source = rawSource as ClickActionSource;

    // ── Port single-click → Node Suggestion ──────────────────────────────────
    if (
      source.objectType === 'port' &&
      source.clickType  === 'SINGLE_CLICK' &&
      source.id
    ) {
      // Close any existing suggestion panel before opening a new one.
      handleNodeSuggestionClose();
      const controller = canvasControllerRef.current;
      if (!controller) { return; }
      const nodeId = (source as any).nodeId as string | undefined;
      if (!nodeId) { return; }
      openNodeSuggestion(nodeId, controller);
      return;
    }

    // ── Node double-click → Properties panel ─────────────────────────────────
    if (source.clickType === 'DOUBLE_CLICK' && source.objectType === 'node' && source.id) {
      openNodePanel(String(source.id));
    }
  }, [openNodePanel, handleNodeSuggestionClose]);

  const handleApplyPropertyChanges = useCallback(
    (propertySet: Record<string, unknown>, appData?: Record<string, unknown>) => {
      const nodeId = (appData as { nodeId?: string } | undefined)?.nodeId;
      const controller = canvasControllerRef.current;

      if (!nodeId || !controller) { return; }

      // Use setNodeParameters (targeted parameter update) rather than the broader
      // setNodeProperties(). The TS declaration is typed as array but the JS impl
      // dispatches the value as-is; a plain object works here.
      controller.setNodeParameters(nodeId, propertySet as unknown as Array<Record<string, unknown>>);

      setIsDirty(true);
    },
    []
  );

  const handleClosePropertiesDialog = useCallback(() => {
    propertiesControllerRef.current = null;
    openPanelNodeIdRef.current = null;
    setIsPanelOpen(false);
    setSelectedNodeId(null);
    setSelectedOperator(null);
    setPropertiesInfo(null);
  }, []);

  const handleControllerHandler = useCallback((propertiesController: any) => {
    propertiesControllerRef.current = propertiesController;
  }, []);

  /**
   * Called by Elyra when a hotspot decoration is clicked on a link.
   * Elyra passes `(object, decorationId, pipelineId)`.
   * The decoration id encodes either `${linkId}-pill` or `${linkId}-addCondition`,
   * so we strip the suffix to recover the real link id and open the tearsheet.
   */
  const handleDecorationAction = useCallback(
    (_object: unknown, decorationId: string, _pipelineId: string): void => {
      // Decoration clicks in read-only mode should not open the tearsheet.
      if (!decorationId) { return; }

      // Pill decoration: "${linkId}-pill"
      // Add-condition decoration: "${linkId}-${CANVAS_ACTIONS.ADD_CONDITION}"
      const pillSuffix = '-pill';
      const addSuffix = `-${CANVAS_ACTIONS.ADD_CONDITION}`;
      let linkId: string | null = null;
      if (decorationId.endsWith(pillSuffix)) {
        linkId = decorationId.slice(0, -pillSuffix.length);
      } else if (decorationId.endsWith(addSuffix)) {
        linkId = decorationId.slice(0, -addSuffix.length);
      }
      if (linkId) { openLinkConditionTearsheet(linkId); }
    },
    [openLinkConditionTearsheet]
  );

  const handlePropertyListener = useCallback((_data: unknown): void => {
    const controller = propertiesControllerRef.current;
    if (!controller) { return; }

    const propertyValues = (controller.getPropertyValues?.() ?? {}) as Record<string, unknown>;
    const attrs: Record<string, OperatorFeature> =
      selectedOperator ? (operatorMetadata[selectedOperator]?.attributes ?? {}) : {};

    const shouldDisable = hasAnyRequiredParamMissing(attrs, propertyValues);

    controller.setSaveButtonDisable?.(shouldDisable);
  }, [operatorMetadata, selectedOperator]);

  // Stable callback so ElyraCanvas's onCanvasControllerReady useEffect
  // does not re-fire on every theme-driven re-render.
  const handleCanvasControllerReady = useCallback((controller: CanvasController) => {
    canvasControllerRef.current = controller;
    // Re-apply link decorations after the D3 SVG has fully rendered.
    // requestAnimationFrame defers until after CommonCanvas's componentDidMount
    // so Elyra's link elements exist in the DOM before setLinkDecorations is called.
    // This restores pill/add-icon decorations on hard reload without requiring a
    // canvas mutation to trigger editActionHandler.
    requestAnimationFrame(() => { reapplyAllLinkDecorations(); });
  }, [reapplyAllLinkDecorations]);

  const rightFlyoutContent = useMemo(() => {
    if (!isPanelOpen || !selectedNodeId || !selectedOperator || !canvasControllerRef.current || !propertiesInfo) {
      return undefined;
    }
    return (
      <CommonProperties
        propertiesInfo={propertiesInfo as any}
        propertiesConfig={{ containerType: 'Custom', rightFlyout: true, applyPropertiesWithoutEdit: true }}
        customPanels={[CommonPropertiesPanelWrapper]}
        callbacks={{
          applyPropertyChanges: handleApplyPropertyChanges,
          closePropertiesDialog: handleClosePropertiesDialog,
          controllerHandler: handleControllerHandler,
          propertyListener: handlePropertyListener,
        }}
      />
    );
  }, [
    isPanelOpen, selectedNodeId, selectedOperator, propertiesInfo,
    handleApplyPropertyChanges, handleClosePropertiesDialog, handleControllerHandler,
    handlePropertyListener,
  ]);

  // ── ReadOnlyCanvas callbacks ──────────────────────────────────────────────

  const handleExitRun = useCallback(() => {
    // Exit the viewer — poll keeps running in background so "View run" can
    // re-enter and pick up live data from Redux executionLogs.
    // Only clear state when run has fully completed.
    setIsRunMode(false);
    if (!isRunning) {
      runPipelineFlowRef.current = null;
      dispatch(setCurrentRun(null));
      dispatch(setExecutionLogs(null));
    }
  }, [isRunning, dispatch]);

  const handleRunAgainFromCanvas = useCallback((newJobRunId: string) => {
    // Run Again: ReadOnlyCanvas already created the new job run and passes
    // the new ID here. runPipelineFlowRef.current is intentionally kept — same flow def reused.
    dispatch(setCurrentRun({ jobId: currentJobId ?? '', jobRunId: newJobRunId }));
    startPoll(newJobRunId);
  }, [currentJobId, dispatch, startPoll]);

  const handleStopFromCanvas = useCallback(() => {
    // Stop: cancel the run and schedule a quick re-poll to pick up Cancelled status.
    stopPoll();
    void cancelJobRun(currentJobRunId ?? '').catch(() => {}).finally(() => {
      startPoll(currentJobRunId ?? '');
    });
  }, [currentJobRunId, stopPoll, startPoll]);

  // ── Guards ────────────────────────────────────────────────────────────────

  // Show ReadOnlyCanvas when a run has been started.
  // runPipelineFlowRef.current is always set synchronously in handleRun before
  // any await, so it is guaranteed to be non-null when isRunMode becomes true.
  if (isRunMode && runPipelineFlowRef.current && currentJobId && currentJobRunId) {
    return (
      <div className={styles.canvasContainer}>
        <ReadOnlyCanvas
          pipelineFlow={runPipelineFlowRef.current}
          jobId={currentJobId}
          jobRunId={currentJobRunId}
          onExit={handleExitRun}
          onRunAgain={handleRunAgainFromCanvas}
          onStop={handleStopFromCanvas}
        />
      </div>
    );
  }

  if (isLoading) {
    return (
      <div className={styles.loadingContainer}>
        <Loading description={intl.formatMessage(messages.loadingCanvas)} />
      </div>
    );
  }

  if (flowError) {
    return (
      <div className={styles.errorContainer}>
        <ErrorEmptyState
          illustrationTheme={isDarkMode ? 'dark' : 'light'}
          title={intl.formatMessage(messages.flowLoadErrorTitle)}
          subtitle={flowError}
          action={{
            text: intl.formatMessage(messages.goToProjects),
            onClick: () => { void navigate(projectId ? `/projects/${projectId}` : '/projects'); },
            renderIcon: ArrowLeft,
            kind: 'tertiary',
          }}
        />
      </div>
    );
  }

  if (!pipelineFlow) {
    return (
      <div className={styles.errorContainer}>
        <ErrorEmptyState
          illustrationTheme={isDarkMode ? 'dark' : 'light'}
          title={intl.formatMessage(messages.pipelineLoadErrorTitle)}
          subtitle={intl.formatMessage(messages.pipelineLoadErrorSubtitle)}
          action={{
            text: intl.formatMessage(messages.goToProjects),
            onClick: () => { void navigate(projectId ? `/projects/${projectId}` : '/projects'); },
            renderIcon: ArrowLeft,
            kind: 'tertiary',
          }}
        />
      </div>
    );
  }

  // ── Render ────────────────────────────────────────────────────────────────

  return (
    <ErrorBoundary
      fallback={
        <div className={styles.errorContainer}>
          <p>{intl.formatMessage(messages.canvasInitError)}</p>
        </div>
      }
    >
      <div className={styles.canvasPage}>
        <div className={styles.canvasContainer}>
          <NotificationPanel
            validationData={validationData}
            canvasControllerRef={canvasControllerRef}
            openNodeProperties={openNodePanel}
            setActivePanelNodeId={setSelectedNodeId}
            onStateChange={handleNotificationStateChange}
            onBottomContent={setBottomPanelContent}
            onTopContent={setTopNotificationBar}
          />
          <ElyraCanvas
            pipelineFlow={pipelineFlow}
            palette={palette}
            canvasConfig={canvasConfig}
            toolbarConfig={toolbarConfig}
            contextMenuHandler={contextMenuHandler}
            editActionHandler={editActionHandler}
            clickActionHandler={clickActionHandler}
            decorationActionHandler={handleDecorationAction}
            onCanvasControllerReady={handleCanvasControllerReady}
            rightFlyoutContent={rightFlyoutContent}
            showRightFlyout={isPanelOpen && !isAboutPanelOpen}
            bottomPanelContent={bottomPanelContent}
            showBottomPanel={showBottomPanel}
            topPanelContent={topNotificationBar}
            showTopPanel={topNotificationBar !== null}
          />
          {isAboutPanelOpen && panelFlow && (
            <FlowInfoPanel
              flow={panelFlow}
              onClose={() => { setIsAboutPanelOpen(false); }}
              onViewFlow={() => { /* already on Canvas */ }}
              onViewProject={() => { void navigate(projectId ? `/projects/${projectId}` : '/projects'); }}
              onEdit={() => { setIsEditOpen(true); }}
            />
          )}
          {currentFlow && (
            <EditDetailsModal
              open={isEditOpen}
              title={intl.formatMessage(messages.editModalTitle)}
              initialValues={{
                name:        currentFlow.name ?? '',
                description: currentFlow.description ?? '',
                tags:        currentFlow.tags ?? [],
              }}
              onCancel={() => { setIsEditOpen(false); }}
              onEdit={(updates) => {
                if (!currentFlow.flow_id) { return Promise.resolve(); }
                return patchFlow(currentFlow.flow_id, updates)
                  .then((res) => {
                    const flowId = currentFlow.flow_id!;
                    dispatch(setCurrentFlow({ ...currentFlow, ...res.data }));
                    dispatch(updateFlow({ flowId, updates: { name: updates.name, description: updates.description, tags: updates.tags } }));
                    setIsEditOpen(false);
                  })
                  .catch(() => {
                    notify.error(intl.formatMessage(messages.saveDetailsError), {
                      subtitle: intl.formatMessage(messages.saveDetailsErrorSubtitle),
                    });
                  });
              }}
            />
          )}
          <FlowRunPropertiesTearsheet
            open={isFlowRunPropertiesOpen}
            onClose={() => { setIsFlowRunPropertiesOpen(false); }}
            onSave={handleSaveFlowRunProperties}
          />
          <FlowRunHistoryTearsheet
            open={isFlowRunHistoryOpen}
            onClose={() => { setIsFlowRunHistoryOpen(false); }}
            flowId={flowId}
            projectId={projectId ?? ''}
          />
          {nodeSuggestion && (
            <NodeSuggestion
              onClose={handleNodeSuggestionClose}
              onSelectNode={handleNodeSuggestionSelect}
              position={nodeSuggestion.position}
              paletteData={nodeSuggestion.paletteData}
              lineStart={nodeSuggestion.lineStart}
              lineEnd={nodeSuggestion.lineEnd}
            />
          )}
          <LinkConditionTearsheet
            open={isLinkConditionOpen}
            onClose={() => {
              setIsLinkConditionOpen(false);
              setActiveLinkId(null);
              setIsMergingLink(false);
            }}
            onSave={handleSaveLinkCondition}
            initialValues={linkConditionForm}
            branchingNodeId={branchingNodeId}
            isMergingNode={isMergingLink}
            inputFeatures={linkInputFeatures}
          />
        </div>
      </div>
    </ErrorBoundary>
  );
}
