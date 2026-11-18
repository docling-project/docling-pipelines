import React, { useCallback, useEffect, useState } from 'react';
import { useIntl } from 'react-intl';
import { useNavigate } from 'react-router-dom';
import { go } from '@/utils';
import { Add, Renew } from '@carbon/icons-react';
import { NoDataEmptyState, ErrorEmptyState } from '@carbon/ibm-products';
import { PageLayout } from '@/components';
import { CreateProjectTearsheet } from '@/components/common/CreateProjectTearsheet';
import { ProjectsTable } from '@/components/Projects';
import type { CreateProjectFormValues, Project, ProjectRow } from '@/types';
import { useAppDispatch, useAppSelector, useTheme } from '@/hooks';
import { generateRoute } from '@/config';
import { createFlow, createProject, deleteProject, getProjects, replaceProject } from '@/services/api';
import * as projectMapper from '@/services/api/mappers/project-mapper';
import * as flowMapper from '@/services/api/mappers/flow-mapper';
import { buildFlowDefinition } from '@/lib/helpers';
import { removeProject, setProject, setProjects, setLoading, setError, clearError } from '@/slices/projectsSlice';
import { setFlow } from '@/slices/flowSlice';
import { selectProjectsArray, selectProjectsLoading, selectProjectsError } from '@/selectors';
import { useNotify } from '@/hooks';
import { messages } from './Projects.messages';
import styles from './Projects.module.scss';

/**
 * Maps a {@link Project} domain model to the UI {@link ProjectRow} shape.
 *
 * @param p - The domain project object from the Redux store.
 * @returns A `ProjectRow` ready for consumption by {@link ProjectsTable}.
 */
function toProjectRow(p: Project): ProjectRow {
  return {
    id: p.id,
    name: p.name,
    description: p.description,
    flows: p.flowCount,
    tags: p.tags,
    lastModified: new Date(p.modifiedOn).toLocaleDateString(),
    lastModifiedRaw: p.modifiedOn,
    createdOn: new Date(p.createdOn).toLocaleDateString(),
    createdOnRaw: p.createdOn,
  };
}

/**
 * Top-level Projects page.
 *
 * Renders one of three states:
 * - **Loading** — {@link ProjectsTable} renders a `DataTableSkeleton` (via its
 *   `isLoading` prop) shaped like the final toolbar/table while the initial fetch
 *   is in-flight — avoids a spinner flash and layout shift once rows arrive.
 * - **Empty state** — `NoDataEmptyState` illustration + "Create Project" tertiary button
 *   when the project list is empty and the fetch has settled.
 * - **Table state** — {@link ProjectsTable} with toolbar (search, refresh, new project),
 *   per-row overflow actions, and inline edit/delete modals.
 *
 * The page uses a two-zone full-bleed layout:
 * - White 88 px title band at the top.
 * - Grey `$layer-01` content zone filling the rest of the viewport.
 *
 * No breadcrumb is shown on this page — it is a top-level root.
 */
export function Projects(): React.JSX.Element {
  const intl = useIntl();
  const { isDarkMode } = useTheme();
  const navigate = useNavigate();
  const dispatch = useAppDispatch();
  const notify = useNotify();

  const projectsArray = useAppSelector(selectProjectsArray);
  const loading = useAppSelector(selectProjectsLoading);
  const error = useAppSelector(selectProjectsError);

  const [tearsheetOpen, setTearsheetOpen] = useState(false);

  /**
   * Fetches the full project list from `GET /api/projects` and stores the
   * results in Redux. Sets loading before the call and clears it on completion.
   * Dispatches `setError` if the request fails.
   */
  const fetchProjects = useCallback((): void => {
    dispatch(setLoading(true));
    getProjects()
      .then((res) => {
        const projectsMap = Object.fromEntries(
          res.data.projects.map((p) => {
            const domain = projectMapper.fromResponse(p);
            return [domain.id, domain];
          })
        );
        dispatch(setProjects(projectsMap));
      })
      .catch(() => {
        dispatch(setError(intl.formatMessage(messages.loadError)));
      })
      .finally(() => {
        dispatch(setLoading(false));
      });
  }, [dispatch, intl]);

  useEffect(() => {
    fetchProjects();
  }, [fetchProjects]);

  /** Derives UI table rows by mapping every cached {@link Project} domain object through {@link toProjectRow}. */
  const rows: ProjectRow[] = projectsArray.map((p) => toProjectRow(p));

  const isEmpty = rows.length === 0;

  /**
   * Handles the tearsheet Create action.
   *
   * Sequence:
   * 1. `POST /api/projects` — creates the project.
   * 2. Dispatches `setProject` to add it to the Redux store immediately.
   * 3. If `flow.flowName` is non-empty, `POST /api/flows` with `container_id` set to the new project ID.
   *
   * On failure, dispatches `setError` so the page renders the error banner,
   * then re-throws so the tearsheet stays open and surfaces the error to its caller.
   *
   * @param project - Validated project form values from step 1 of the tearsheet.
   * @param flow    - Optional flow form values from step 2 (all fields may be empty).
   * @returns Promise that resolves when all API calls are complete.
   */
  const handleTearsheetSubmit = async (
    project: CreateProjectFormValues,
    flow: { flowName: string; flowDescription: string; flowTags: string[] }
  ): Promise<void> => {
    try {
      const projectRes = await createProject(projectMapper.toCreateRequest(project));
      const created = projectMapper.fromResponse(projectRes.data);

      dispatch(setProject({
        projectId: created.id,
        project: created,
      }));

      if (flow.flowName.trim()) {
        const flowRes = await createFlow(
          flowMapper.toCreateRequest(
            { name: flow.flowName, description: flow.flowDescription, tags: flow.flowTags },
            created.id,
            buildFlowDefinition(flow.flowName, flow.flowDescription)
          )
        );

        const newFlowRow = flowMapper.fromResponse(flowRes.data);

        // Put the new flow into state.flow.items so the breadcrumb can resolve
        // the flow name immediately (makeSelectFlowName reads from this map).
        dispatch(setFlow({ flowId: newFlowRow.flow_id, flow: newFlowRow }));

        // Bump the project's flow count in the store so the table column reflects
        // the newly created flow without a full re-fetch.
        dispatch(setProject({
          projectId: created.id,
          project: { ...created, flowCount: created.flowCount + 1 },
        }));

        // Navigate directly to the canvas for the new flow.
        go(navigate, generateRoute.canvas(newFlowRow.flow_id, created.id));
      } else {
        go(navigate, generateRoute.projectDetail(created.id));
      }
      notify.success(intl.formatMessage(messages.createSuccess, { name: project.name }));
    } catch (err) {
      dispatch(setError(intl.formatMessage(messages.createError)));
      notify.error(intl.formatMessage(messages.createErrorToast));
      throw err;
    }
  };

  /**
   * Navigates to the project detail page for the given project ID.
   *
   * @param projectId - The `project_id` of the project row that was clicked.
   */
  const handleOpenProject = (projectId: string): void => {
    go(navigate, generateRoute.projectDetail(projectId));
  };

  /** Re-fetches the project list from `GET /api/projects` and updates the Redux store. */
  const handleRefresh = (): void => {
    fetchProjects();
  };

  /**
   * Calls `DELETE /api/projects/:id` via the BFF, then dispatches `removeProject`
   * so the table row disappears immediately without a full re-fetch.
   * Dispatches `setError` on failure so the page renders an error banner;
   * re-throws so the modal stays open and clears its loading state.
   *
   * @param projectId - The `project_id` of the project to delete.
   * @returns Promise that resolves once the store has been updated.
   */
  const handleDeleteProject = (projectId: string): Promise<void> => {
    const projectName =
      projectsArray.find((p) => p.id === projectId)?.name ?? intl.formatMessage(messages.defaultProjectName);
    return deleteProject(projectId)
      .then((): void => {
        dispatch(removeProject(projectId));
        notify.success(intl.formatMessage(messages.deleteSuccess, { name: projectName }));
      })
      .catch((err: unknown) => {
        dispatch(setError(intl.formatMessage(messages.deleteError)));
        notify.error(intl.formatMessage(messages.deleteErrorToast, { name: projectName }));
        throw err;
      });
  };

  /**
   * Calls `PUT /api/projects/:id` via the BFF with the full replacement payload,
   * then dispatches `setProject` with the updated response so the table row and
   * edit modal description both reflect the saved values without a full re-fetch.
   * Dispatches `setError` on failure so the page renders an error banner;
   * re-throws so the modal stays open and clears its loading state.
   *
   * @param projectId - The `project_id` of the project to update.
   * @param updates   - The new name, description, and tags to persist.
   * @returns Promise that resolves once the store has been updated.
   */
  const handleEditProject = async (
    projectId: string,
    updates: { name: string; description: string; tags: string[] }
  ): Promise<void> => {
    dispatch(clearError());
    try {
      const res = await replaceProject(projectId, projectMapper.toUpdateRequest(updates));
      const updated = projectMapper.fromResponse(res.data);
      dispatch(setProject({
        projectId: updated.id,
        project: updated,
      }));
      notify.success(intl.formatMessage(messages.updateSuccess, { name: updates.name }));
    } catch (err) {
      dispatch(setError(intl.formatMessage(messages.updateError)));
      notify.error(intl.formatMessage(messages.updateErrorToast));
      throw err;
    }
  };

  return (
    <PageLayout fullBleed>
      {/* White title band */}
      <div className={styles.titleZone}>
        <h1 className={styles.title}>{intl.formatMessage(messages.title)}</h1>
      </div>

      {/* Grey content zone — error / empty state / table (with built-in skeleton loading) */}
      <div className={styles.contentZone}>
        {error ? (
          <div className={styles.centeredState}>
            <ErrorEmptyState
              illustrationTheme={isDarkMode ? 'dark' : 'light'}
              title={intl.formatMessage(messages.errorStateTitle)}
              subtitle={error}
              action={{
                text: intl.formatMessage(messages.tryAgain),
                onClick: () => { dispatch(clearError()); fetchProjects(); },
                renderIcon: Renew,
                kind: 'tertiary',
              }}
            />
          </div>
        ) : isEmpty && !loading ? (
          <div className={styles.centeredState}>
            <NoDataEmptyState
              illustrationTheme={isDarkMode ? 'dark' : 'light'}
              illustrationPosition="top"
              size="sm"
              title={intl.formatMessage(messages.emptyTitle)}
              action={{
                text: intl.formatMessage(messages.createProject),
                onClick: () => { setTearsheetOpen(true); },
                renderIcon: Add,
                kind: 'tertiary',
              }}
            />
          </div>
        ) : (
          <ProjectsTable
            rows={rows}
            isLoading={loading}
            onNewProject={() => { setTearsheetOpen(true); }}
            onOpenProject={handleOpenProject}
            onRefresh={handleRefresh}
            onDeleteProject={handleDeleteProject}
            onEditProject={handleEditProject}
          />
        )}
      </div>

      <CreateProjectTearsheet
        open={tearsheetOpen}
        onClose={() => { setTearsheetOpen(false); }}
        onSubmit={handleTearsheetSubmit}
      />
    </PageLayout>
  );
}
