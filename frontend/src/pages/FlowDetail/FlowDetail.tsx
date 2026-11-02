import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { useIntl } from 'react-intl';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { go } from '@/utils';
import {
  Button,
  IconButton,
  InlineLoading,
} from '@carbon/react';
import { View, Information, Renew as RenewIcon } from '@carbon/icons-react';
import { ErrorEmptyState, NoDataEmptyState } from '@carbon/ibm-products';
import { PageLayout } from '@/components';
import { DeleteModal, EditDetailsModal } from '@/components/common';
import { getFlow, getProject, patchFlow, getJobRuns, deleteJobRun } from '@/services/api';
import { cancelJobRun } from '@/services/api/actions/job-run-actions';
import * as flowMapper from '@/services/api/mappers/flow-mapper';
import * as projectMapper from '@/services/api/mappers/project-mapper';
import { API_STATUS_MAP } from '@/constants/flowStatus';
import { setFlow, updateFlow, setLoading, setError, setCurrentFlow } from '@/slices/flowSlice';
import { setProject } from '@/slices/projectsSlice';
import { makeSelectFlow, makeSelectProject, selectCurrentFlow } from '@/selectors';
import { useAppDispatch, useAppSelector, useNotify, useTheme } from '@/hooks';
import { useRecentlyVisited } from '@/hooks/useRecentlyVisited';
import { ROUTES, generateRoute } from '@/config';
import { useBreadcrumbActions } from '@/contexts';
import { formatEpochToDisplay, formatElapsedTime } from '@/utils/dateTimeUtils';
import { FlowInfoPanel } from '@/components/common/FlowInfoPanel';
import { FlowMetrics, FlowRunsTable } from '@/components/FlowDetail';
import type { RunMetrics, RunRow } from '@/components/FlowDetail';
import { messages } from './FlowDetail.messages';
import styles from './FlowDetail.module.scss';

// ─── Local helpers ─────────────────────────────────────────────────────────────

/** Converts a raw API status string to a {@link RunStatus}. Unknown values → `'run_with_issues'`. */
function toRunStatus(apiStatus: string): RunRow['status'] {
  return (API_STATUS_MAP[apiStatus] ?? 'run_with_issues') as RunRow['status'];
}

// ─── Component ─────────────────────────────────────────────────────────────────

/**
 * Flow detail page — rendered at `/projects/:projectId/:flowId`.
 *
 * **Responsibilities (this component only):**
 * - Bootstrap: reads `flowRow` from `state.flow.items[flowId]`; calls
 *   `GET /api/flows/:id` only on a cache miss (deep link / page refresh).
 * - Fetches job runs via `GET /api/job-runs?job_id=:flowId` and holds them in
 *   local state (runs are transient — not persisted to Redux).
 * - Computes {@link RunMetrics} from the run list via `useMemo`.
 * - Injects the ⓘ Info button into the breadcrumb bar while the panel is closed.
 * - Dispatches `patchFlow` + optimistic `updateFlow` on edit-modal save.
 * - Dispatches `deleteJobRun` + local state update on run-delete confirm.
 *
 * **Rendering is delegated to:**
 * - {@link FlowMetrics}   — five run-count tiles
 * - {@link FlowRunsTable} — filterable runs table with toolbar
 * - {@link FlowInfoPanel} — "About flow" sliding panel (conditionally rendered)
 */
export function FlowDetail(): React.JSX.Element | null {
  const intl = useIntl();
  const { flow_id: flowId } = useParams<{ flow_id: string }>();
  const [searchParams] = useSearchParams();
  const projectId = searchParams.get('project_id') ?? '';
  const navigate = useNavigate();
  const dispatch = useAppDispatch();
  const notify = useNotify();
  const { setActions } = useBreadcrumbActions();
  const { addEntry, removeEntry } = useRecentlyVisited();
  const { isDarkMode } = useTheme();

  // ── Flow row from store ──────────────────────────────────────────────────
  const flowRow = useAppSelector(makeSelectFlow(flowId));
  // Used to keep currentFlow in sync when the user edits flow details here
  // so that Canvas reflects the new name without a re-fetch.
  const currentFlow = useAppSelector(selectCurrentFlow);

  // ── Project name for the side panel display label ────────────────────────
  // projectId comes from the ?project_id= query param; resolve the human-readable
  // name from the store so the panel shows "My Project" instead of a raw UUID.
  const project = useAppSelector(makeSelectProject(projectId));
  const projectName = project?.name ?? projectId;

  // ── Bootstrap: fetch project if not in store (deep link / page refresh) ──
  // On a hard refresh the projects slice is empty — nothing has called getProjects()
  // yet. Fetch the single project by ID so the breadcrumb can show the name instead
  // of the raw UUID.
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

  // ── Run rows in local state — not persisted to store (runs are transient) ─
  const [runs, setRuns] = useState<RunRow[]>([]);
  const [runsLoading, setRunsLoading] = useState(false);
  const [runsError, setRunsError] = useState<string | null>(null);
  const [panelOpen, setPanelOpen] = useState(false);
  const [editOpen, setEditOpen] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<RunRow | null>(null);

  // ── Bootstrap: fetch flow if not in store (deep link / page refresh) ───
  useEffect(() => {
    if (!flowId || flowRow) { return; }
    const abortController = new AbortController();
    dispatch(setLoading(true));
    getFlow(flowId)
      .then((res) => {
        if (abortController.signal.aborted) { return; }
        const row = flowMapper.fromResponse(res.data);
        dispatch(setFlow({ flowId: row.flow_id || flowId, flow: row }));
      })
      .catch((err: { response?: { status?: number } } | unknown) => {
        if (abortController.signal.aborted) { return; }
        removeEntry(`flow-${flowId}`);
        const axiosErr = err as { response?: { status?: number } };
        if (axiosErr?.response?.status === 404) {
          go(navigate, ROUTES.ERROR, {
            state: { message: intl.formatMessage(messages.flowNotFound), statusCode: 404 },
            replace: true,
          });
        } else {
          const loadErrorMessage = intl.formatMessage(messages.flowLoadError);
          dispatch(setError(loadErrorMessage));
          go(navigate, ROUTES.ERROR, { state: { message: loadErrorMessage, statusCode: 500 }, replace: true });
        }
      })
      .finally(() => {
        if (!abortController.signal.aborted) {
          dispatch(setLoading(false));
        }
      });
    return () => { abortController.abort(); };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [flowId, flowRow, dispatch]);

  // Record this flow as recently visited once its name is available.
  // Runs only when the flow ID changes — addEntry is stable (useCallback []).
  useEffect(() => {
    if (!flowRow?.flow_id || !flowRow.name) { return; }
    addEntry({
      id: `flow-${flowRow.flow_id}`,
      label: flowRow.name,
      path: generateRoute.flowDetail(flowRow.flow_id, flowRow.project_id),
      type: 'flow',
    });
  // eslint-disable-next-line react-hooks/exhaustive-deps -- flowRow.name/.path intentionally omitted; re-recording on label change is unnecessary
  }, [flowRow?.flow_id, addEntry]);

  // ── Fetch job runs via GET /api/job-runs?job_id=:flowId ─────────────────
  // Runs are kept in local state — they are transient and do not need to
  // survive navigation. fetchRuns is memoised so the effect dep array is stable.
  const fetchRuns = useCallback((jobId: string): void => {
    setRunsLoading(true);
    setRunsError(null);
    getJobRuns({ job_id: jobId })
      .then((res) => {
        const rows: RunRow[] = res.data.list.map((item) => ({
          run_id:           item.job_run_id,
          start_time:       formatEpochToDisplay(item.start_time),
          start_time_epoch: item.start_time,
          status:           toRunStatus(item.status),
          duration:         formatElapsedTime(item.duration),
          duration_seconds: item.duration,
        }));
        setRuns(rows);
      })
      .catch(() => {
        setRunsError(intl.formatMessage(messages.runsLoadError));
      })
      .finally(() => {
        setRunsLoading(false);
      });
  }, [intl]);

  useEffect(() => {
    if (flowId) { fetchRuns(flowId); }
  }, [flowId, fetchRuns]);

  // ── Inject ⓘ Info button into the breadcrumb actions slot ───────────────
  // Always visible — isSelected reflects panel open state; click toggles panel.
  // Cleanup fn restores null so the slot is empty when the page unmounts.
  useEffect(() => {
    setActions(
      <IconButton
        kind="ghost"
        size="sm"
        label={intl.formatMessage(messages.aboutFlow)}
        align="bottom-end"
        isSelected={panelOpen}
        onClick={() => { setPanelOpen((prev) => !prev); }}
      >
        <Information size={16} />
      </IconButton>
    );
    return () => { setActions(null); };
  }, [panelOpen, setActions, intl]);

  // ── Derive RunMetrics from local run state ───────────────────────────────
  // Re-computed only when runs changes — each status is a single filter pass.
  const metrics: RunMetrics = useMemo(
    () => ({
      total:           runs.length,
      run:             runs.filter((r) => r.status === 'run').length,
      in_progress:     runs.filter((r) => r.status === 'in_progress').length,
      run_with_issues: runs.filter((r) => r.status === 'run_with_issues').length,
      failed:          runs.filter((r) => r.status === 'failed').length,
      cancelled:       runs.filter((r) => r.status === 'cancelled').length,
    }),
    [runs]
  );

  // ── Handlers ─────────────────────────────────────────────────────────────

  /** Navigates to the Canvas editor for the current flow. */
  const handleViewFlow = (): void => {
    if (flowId) { go(navigate, generateRoute.canvas(flowId, projectId)); }
  };

  /** Navigates to the run details (ReadOnlyCanvas) page for a specific run. */
  const handleViewRun = (runId: string): void => {
    if (flowId) { void navigate(generateRoute.runDetails(flowId, runId, projectId)); }
  };

  /**
   * Cancels an in-progress run and refreshes the run list so the status updates.
   */
  const handleCancelRun = (runId: string): void => {
    void cancelJobRun(runId).finally(() => {
      if (flowId) { fetchRuns(flowId); }
    });
  };

  /** Navigates back to the ProjectDetail page for the parent project. */
  const handleViewProject = (): void => {
    if (projectId) { go(navigate, generateRoute.projectDetail(projectId)); }
  };

  /**
   * Persists name/description/tag edits via `PATCH /api/flows/:id`, then applies
   * an optimistic update to the Redux store so the page reflects the change
   * immediately without a re-fetch.
   */
  const handleEditSave = async (
    id: string,
    updates: { name: string; description: string; tags: string[] }
  ): Promise<void> => {
    await patchFlow(id, flowMapper.toPatchRequest(updates));
    dispatch(updateFlow({ flowId: id, updates: { name: updates.name, description: updates.description, tags: updates.tags } }));
    // Also keep currentFlow in sync so the Canvas page reflects the new name
    // without requiring a re-fetch when the user navigates there next.
    if (currentFlow?.flow_id === id) {
      dispatch(setCurrentFlow({ ...currentFlow, name: updates.name, description: updates.description, tags: updates.tags }));
    }
    setEditOpen(false);
  };

  /**
   * Confirms deletion of the run currently set as `deleteTarget`.
   * Removes the row from local state on success; shows a toast on failure.
   * No-ops if `deleteTarget` is null (modal was closed before confirm fired).
   */
  const handleDeleteRunConfirm = async (): Promise<void> => {
    if (!deleteTarget) { return; }
    try {
      await deleteJobRun(deleteTarget.run_id);
      setRuns((prev) => prev.filter((r) => r.run_id !== deleteTarget.run_id));
      setDeleteTarget(null);
      notify.success(intl.formatMessage(messages.deleteRunSuccess, { id: deleteTarget.run_id }));
    } catch {
      setDeleteTarget(null);
      notify.error(intl.formatMessage(messages.deleteRunError), {
        subtitle: intl.formatMessage(messages.deleteRunErrorSubtitle),
      });
    }
  };

  // Show spinner while fetch is in flight or before redirect fires
  if (!flowRow) {
    return (
      <PageLayout fullBleed>
        <div className={styles.page}>
          <InlineLoading description={intl.formatMessage(messages.loading)} className={styles.loading} />
        </div>
      </PageLayout>
    );
  }

  // Derive the panel data shape from the store row.
  const panelFlow = {
    flow_id:      flowRow.flow_id,
    name:         flowRow.name,
    description:  flowRow.description,
    tags:         flowRow.tags,
    created_on:   flowRow.created_on ? new Intl.DateTimeFormat(undefined, { dateStyle: 'short' }).format(new Date(flowRow.created_on)) : '',
    modified_on:  flowRow.modified_on ? new Intl.DateTimeFormat(undefined, { dateStyle: 'short' }).format(new Date(flowRow.modified_on)) : '',
    project_name: projectName,
  };

  // ── Render ───────────────────────────────────────────────────────────────
  return (
    <PageLayout fullBleed>
      <div className={styles.page}>

        {/* White header */}
        <div className={panelOpen ? `${styles.headerZone} ${styles.headerZoneWithPanel}` : styles.headerZone}>
          <div className={styles.titleRow}>
            <h1 className={styles.flowName}>{intl.formatMessage(messages.runsTitle, { name: flowRow.name })}</h1>
            <Button kind="tertiary" size="sm" renderIcon={View} onClick={handleViewFlow}>
              {intl.formatMessage(messages.viewFlow)}
            </Button>
          </div>
        </div>

        {/* Grey content */}
        <div className={panelOpen ? `${styles.contentZone} ${styles.contentZoneWithPanel}` : styles.contentZone}>
          {runsError ? (
            <div className={styles.centeredState}>
              <ErrorEmptyState
                illustrationTheme={isDarkMode ? 'dark' : 'light'}
                title={intl.formatMessage(messages.runsErrorTitle)}
                subtitle={runsError}
                action={{
                  text: intl.formatMessage(messages.tryAgain),
                  onClick: () => { if (flowId) { fetchRuns(flowId); } },
                  renderIcon: RenewIcon,
                  kind: 'tertiary',
                }}
              />
            </div>
          ) : !runsLoading && runs.length === 0 ? (
            <div className={styles.centeredState}>
              <NoDataEmptyState
                illustrationTheme={isDarkMode ? 'dark' : 'light'}
                illustrationPosition="top"
                size="sm"
                title={intl.formatMessage(messages.emptyTitle)}
                subtitle={intl.formatMessage(messages.emptySubtitle)}
              />
            </div>
          ) : (
            <>
              <FlowMetrics metrics={metrics} />
              <FlowRunsTable
                runs={runs}
                isLoading={runsLoading}
                onRefresh={() => { if (flowId) { fetchRuns(flowId); } }}
                onDeleteRun={setDeleteTarget}
                onCancelRun={handleCancelRun}
                onViewRun={handleViewRun}
              />
            </>
          )}
        </div>

        {/* About flow side panel */}
        {panelOpen && (
          <FlowInfoPanel
            flow={panelFlow}
            onClose={() => { setPanelOpen(false); }}
            onViewFlow={handleViewFlow}
            onViewProject={handleViewProject}
            onEdit={() => { setEditOpen(true); }}
          />
        )}

      </div>

      <EditDetailsModal
        open={editOpen}
        title={intl.formatMessage(messages.editModalTitle)}
        initialValues={{ name: flowRow.name, description: flowRow.description, tags: flowRow.tags }}
        onCancel={() => { setEditOpen(false); }}
        onEdit={(updates) => handleEditSave(flowRow.flow_id, updates)}
      />

      <DeleteModal
        open={deleteTarget !== null}
        assetType={intl.formatMessage(messages.deleteAssetType)}
        assetName={deleteTarget?.start_time ?? ''}
        onCancel={() => { setDeleteTarget(null); }}
        onDelete={handleDeleteRunConfirm}
      />

    </PageLayout>
  );
}
