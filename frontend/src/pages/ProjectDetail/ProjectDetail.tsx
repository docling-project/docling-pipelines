import React, { useCallback, useEffect, useState } from 'react';
import { useIntl } from 'react-intl';
import { useNavigate, useParams } from 'react-router-dom';
import { go } from '@/utils';
import { Tag } from '@carbon/react';
import { Add, ChevronUp, ChevronDown } from '@carbon/icons-react';
import { NoDataEmptyState } from '@carbon/ibm-products';
import { PageLayout } from '@/components';
import { CreateFlowTearsheet, FlowsTable } from '@/components/ProjectDetail';
import { buildFlowDefinition } from '@/lib/helpers';
import { createFlow, patchFlow, deleteFlow, getProject, getFlowsByProjectId } from '@/services/api';
import * as projectMapper from '@/services/api/mappers/project-mapper';
import * as flowMapper from '@/services/api/mappers/flow-mapper';
import type { CreateFlowFormValues } from '@/types';
import { setProject, setLoading, setError } from '@/slices/projectsSlice';
import { setFlows, setFlow, updateFlow, removeFlow, setLoading as setFlowsLoading, setError as setFlowsError } from '@/slices/flowSlice';
import {
  makeSelectProject,
  selectFlowsArray,
  selectFlowLoading,
} from '@/selectors';
import { useAppDispatch, useAppSelector, useTheme, useNotify } from '@/hooks';
import { useRecentlyVisited } from '@/hooks/useRecentlyVisited';
import { ROUTES, generateRoute } from '@/config';
import { messages } from './ProjectDetail.messages';
import styles from './ProjectDetail.module.scss';

/**
 * Project detail page — rendered at `/projects/:projectId`.
 *
 * Layout (two-zone, full-bleed):
 * - **White header zone** — project name, description + meta, tags + collapse chevron.
 *   Rendered as soon as `project` resolves from the store, even while flows are
 *   still loading — the project fetch and the flows fetch are independent.
 * - **Grey content zone** — {@link FlowsTable}, which renders its own
 *   `DataTableSkeleton` (via its `isLoading` prop) whenever a flows fetch is
 *   in-flight (initial load or manual Refresh), or `NoDataEmptyState` once
 *   loaded with zero flows. This avoids a spinner flash, layout shift, and
 *   stale rows briefly showing during navigation between projects.
 *
 * Flows are stored in `state.flow.items` (mirroring how projects are stored in
 * `state.projects.items`). Navigating away and back re-uses the cached rows;
 * the Refresh button triggers a full re-fetch.
 */
export function ProjectDetail(): React.JSX.Element | null {
  const intl = useIntl();
  // project_id in the URL is the raw UUID from the API (e.g. "abc-123").
  const { project_id: projectId } = useParams<{ project_id: string }>();
  const navigate = useNavigate();
  const { isDarkMode } = useTheme();
  const dispatch = useAppDispatch();
  const notify = useNotify();
  const { addEntry, removeEntry } = useRecentlyVisited();

  // ── Project from store ───────────────────────────────────────────────────
  const project = useAppSelector(makeSelectProject(projectId));
  // ── Flows from store ─────────────────────────────────────────────────────
  const flows = useAppSelector(selectFlowsArray);
  const flowsLoading = useAppSelector(selectFlowLoading);

  const [collapsed, setCollapsed] = useState(false);
  const [createFlowOpen, setCreateFlowOpen] = useState(false);
  const [createFlowLoading, setCreateFlowLoading] = useState(false);
  const [createFlowError, setCreateFlowError] = useState<string | null>(null);

  // ── Bootstrap: fetch project if this specific project isn't in the store ─
  useEffect(() => {
    if (!projectId || project) { return; }
    let cancelled = false;
    dispatch(setLoading(true));
    getProject(projectId)
      .then((res) => {
        if (cancelled) { return; }
        const domain = projectMapper.fromResponse(res.data);
        dispatch(setProject({ projectId: domain.id, project: domain }));
      })
      .catch((err: { response?: { status?: number } } | unknown) => {
        if (cancelled) { return; }
        removeEntry(`project-${projectId}`);
        const axiosErr = err as { response?: { status?: number } };
        if (axiosErr?.response?.status === 404) {
          go(navigate, ROUTES.ERROR, {
            state: { message: intl.formatMessage(messages.projectNotFound), statusCode: 404 },
            replace: true,
          });
        } else {
          const loadErrorMessage = intl.formatMessage(messages.projectLoadError);
          dispatch(setError(loadErrorMessage));
          go(navigate, ROUTES.ERROR, { state: { message: loadErrorMessage, statusCode: 500 }, replace: true });
        }
      })
      .finally(() => {
        if (!cancelled) {
          dispatch(setLoading(false));
        }
      });
    return () => { cancelled = true; };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId]);

  // ── Fetch flows for this project, write to store ─────────────────────────
  const fetchFlows = useCallback((projectId: string): void => {
    dispatch(setFlowsLoading(true));
    getFlowsByProjectId(projectId)
      .then((res) => {
        const flowsMap = Object.fromEntries(
          res.data.flows.map((f) => {
            const row = flowMapper.fromResponse(f);
            return [row.flow_id, row];
          })
        );
        dispatch(setFlows(flowsMap));
      })
      .catch(() => {
        dispatch(setFlowsError(intl.formatMessage(messages.flowsLoadError)));
      })
      .finally(() => {
        dispatch(setFlowsLoading(false));
      });
  }, [dispatch, intl]);

  useEffect(() => {
    if (project?.id) { fetchFlows(project.id); }
  }, [project?.id, fetchFlows]);

  // Keep the project's flowCount in sync with the authoritative flows list
  // returned by fetchFlows — that list is always freshly re-fetched on mount,
  // including when navigating back from Canvas after creating/editing a flow
  // there. This corrects the header count in cases the optimistic increments
  // in handleFlowSubmit/handleDeleteFlow don't cover (e.g. flows created or
  // removed from elsewhere). No-ops once the count already matches.
  useEffect(() => {
    if (!project || flowsLoading) { return; }
    if (project.flowCount === flows.length) { return; }
    dispatch(setProject({
      projectId: project.id,
      project: { ...project, flowCount: flows.length },
    }));
  }, [project, flows.length, flowsLoading, dispatch]);

  // Record this project as recently visited once its name is available.
  // Runs only when the project ID changes — addEntry is stable (useCallback []).
  useEffect(() => {
    if (!project) { return; }
    addEntry({
      id: `project-${project.id}`,
      label: project.name,
      path: generateRoute.projectDetail(project.id),
      type: 'project',
    });
  // eslint-disable-next-line react-hooks/exhaustive-deps -- project.name/.path intentionally omitted; re-recording on label change is unnecessary
  }, [project?.id, addEntry]);

  const hasFlows = flows.length > 0;

  // ── Handlers ─────────────────────────────────────────────────────────────
  const handleCreateFlow = (): void => {
    setCreateFlowError(null);
    setCreateFlowOpen(true);
  };

  const handleFlowTearsheetClose = (): void => {
    setCreateFlowError(null);
    setCreateFlowOpen(false);
  };

  const handleFlowSubmit = async (values: CreateFlowFormValues): Promise<void> => {
    setCreateFlowLoading(true);
    setCreateFlowError(null);
    try {
      const response = await createFlow(
        flowMapper.toCreateRequest(values, project?.id ?? '', buildFlowDefinition(values.name, values.description))
      );
      const newRow = flowMapper.fromResponse(response.data);
      dispatch(setFlow({ flowId: newRow.flow_id, flow: newRow }));
      setCreateFlowOpen(false);
      notify.success(intl.formatMessage(messages.createFlowSuccess, { name: values.name }));
      if (response.data.flow_id) {
        go(navigate, generateRoute.canvas(response.data.flow_id, project?.id ?? projectId ?? ''));
      }
    } catch (err) {
      const message = err instanceof Error ? err.message : intl.formatMessage(messages.unexpectedError);
      setCreateFlowError(message);
      notify.error(intl.formatMessage(messages.createFlowError), { subtitle: message });
    } finally {
      setCreateFlowLoading(false);
    }
  };

  const handleOpenFlow = (flowId: string): void => {
    go(navigate, generateRoute.canvas(flowId, project?.id ?? projectId ?? ''));
  };

  const handleOpenRuns = (flowId: string): void => {
    go(navigate, generateRoute.flowDetail(flowId, project?.id ?? projectId ?? ''));
  };

  const handleDeleteFlow = (flowId: string): Promise<void> => {
    const flowName = flows.find((f) => f.flow_id === flowId)?.name ?? intl.formatMessage(messages.defaultFlowName);
    return deleteFlow(flowId)
      .then((): void => {
        dispatch(removeFlow(flowId));
        notify.success(intl.formatMessage(messages.deleteFlowSuccess, { name: flowName }));
        // Decrement the project's flow count in the store so the header reflects
        // the deletion without a full re-fetch.
        if (project) {
          dispatch(setProject({
            projectId: project.id,
            project: { ...project, flowCount: Math.max(0, project.flowCount - 1) },
          }));
        }
      })
      .catch((err: unknown) => {
        notify.error(intl.formatMessage(messages.deleteFlowError, { name: flowName }));
        throw err;
      });
  };

  const handleEditFlow = (
    flowId: string,
    updates: { name: string; description: string; tags: string[] }
  ): Promise<void> =>
    patchFlow(flowId, flowMapper.toPatchRequest(updates))
      .then((): void => {
        dispatch(updateFlow({ flowId, updates: { name: updates.name, description: updates.description, tags: updates.tags } }));
        notify.success(intl.formatMessage(messages.updateFlowSuccess, { name: updates.name }));
      })
      .catch((err: unknown) => {
        notify.error(intl.formatMessage(messages.updateFlowError));
        throw err;
      });

  const handleRefresh = (): void => {
    if (project?.id) { fetchFlows(project.id); }
  };

  // Nothing to render yet — project fetch is in flight or a redirect is about
  // to fire. No spinner here: this window is brief and the project header has
  // no natural skeleton shape, so returning null avoids adding a new flicker
  // of its own.
  if (!project) {
    return null;
  }

  const createdOn = new Date(project.createdOn).toLocaleDateString();
  const lastUpdated = new Date(project.modifiedOn).toLocaleDateString();

  return (
    <PageLayout fullBleed>
      <div className={styles.page}>

        {/* ── White project header ── */}
        <div className={styles.headerZone}>
          <h1 className={styles.projectName}>{project.name}</h1>

          {!collapsed && (
            <div className={styles.detailsRow}>
              <p className={styles.description}>{project.description ?? ''}</p>
              <div className={styles.meta}>
                <p className={styles.metaItem}>
                  {intl.formatMessage(messages.created, {
                    date: createdOn,
                    b: (chunks: React.ReactNode) => <b>{chunks}</b>,
                  })}
                </p>
                <p className={styles.metaItem}>
                  {intl.formatMessage(messages.lastUpdated, {
                    date: lastUpdated,
                    b: (chunks: React.ReactNode) => <b>{chunks}</b>,
                  })}
                </p>
                <p className={styles.metaItem}>
                  {intl.formatMessage(messages.flows, {
                    count: project.flowCount,
                    b: (chunks: React.ReactNode) => <b>{chunks}</b>,
                  })}
                </p>
              </div>
            </div>
          )}

          <div className={styles.collapseBar}>
            <div className={styles.tagsRow}>
              {project.tags.map((tag) => (
                <Tag key={tag} type="blue" size="sm">{tag}</Tag>
              ))}
            </div>
            <button
              type="button"
              aria-label={intl.formatMessage(collapsed ? messages.expandDetails : messages.collapseDetails)}
              onClick={() => { setCollapsed((c) => !c); }}
            >
              {collapsed ? <ChevronDown size={16} /> : <ChevronUp size={16} />}
            </button>
          </div>
        </div>

        {/* ── Grey content zone ── */}
        <div className={styles.contentZone}>
          {hasFlows || flowsLoading ? (
            <FlowsTable
              rows={flows}
              isLoading={flowsLoading}
              onNewFlow={handleCreateFlow}
              onOpenFlow={handleOpenFlow}
              onOpenRuns={handleOpenRuns}
              onRefresh={handleRefresh}
              onEditFlow={handleEditFlow}
              onDeleteFlow={handleDeleteFlow}
            />
          ) : (
            <NoDataEmptyState
              className={styles.emptyState}
              illustrationTheme={isDarkMode ? 'dark' : 'light'}
              illustrationPosition="top"
              size="sm"
              title={intl.formatMessage(messages.emptyTitle)}
              action={{
                text: intl.formatMessage(messages.createFlow),
                onClick: handleCreateFlow,
                renderIcon: Add,
                kind: 'tertiary',
              }}
            />
          )}
        </div>

      </div>

      <CreateFlowTearsheet
        open={createFlowOpen}
        onClose={handleFlowTearsheetClose}
        onSubmit={(values) => { void handleFlowSubmit(values); }}
        isLoading={createFlowLoading}
        error={createFlowError}
        existingNames={flows.map((f) => f.name)}
      />

    </PageLayout>
  );
}
