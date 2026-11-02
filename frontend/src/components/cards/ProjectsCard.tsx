import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Button } from '@carbon/react';
import { Add } from '@carbon/icons-react';
import { useIntl } from 'react-intl';
import { ROUTES, generateRoute } from '@/config';
import { go } from '@/utils';
import { useAppDispatch, useAppSelector, useNotify } from '@/hooks';
import { getProjects, createProject, createFlow } from '@/services/api';
import * as projectMapper from '@/services/api/mappers/project-mapper';
import * as flowMapper from '@/services/api/mappers/flow-mapper';
import { buildFlowDefinition } from '@/lib/helpers';
import type { CreateProjectFormValues } from '@/types';
import { setProjects, setProject, setLoading, setError } from '@/slices/projectsSlice';
import { setFlow } from '@/slices/flowSlice';
import { selectProjectsArray, selectProjectsLoading, selectProjectsError } from '@/selectors';
import { formatRelativeTime } from '@/utils/formatRelativeTime';
import { CreateProjectTearsheet } from '../common/CreateProjectTearsheet';
import { HomeCard } from '../HomeCard';
import { messages } from './ProjectsCard.messages';
import cardStyles from '../HomeCard/HomeCard.module.scss';

const MAX_ROWS = 5;

/**
 * Home page card showing the 5 most recently modified projects.
 *
 * - Fetches projects on mount via `GET /api/projects?limit=5`.
 * - The `+` icon in the card header opens {@link CreateProjectTearsheet} directly.
 * - On tearsheet submit: creates the project, optionally creates a flow, dispatches
 *   both to the Redux store, then navigates to the canvas (flow) or project detail.
 * - Sorted client-side by `modifiedOn` (ISO 8601, descending).
 * - Renders a "Create project" CTA in the empty state when no projects exist.
 */
export function ProjectsCard(): React.JSX.Element {
  const intl = useIntl();
  const navigate = useNavigate();
  const dispatch = useAppDispatch();
  const notify = useNotify();

  const projects = useAppSelector(selectProjectsArray);
  const loading = useAppSelector(selectProjectsLoading);
  const error = useAppSelector(selectProjectsError);

  const [tearsheetOpen, setTearsheetOpen] = useState(false);

  useEffect(() => {
    dispatch(setLoading(true));
    getProjects({ limit: MAX_ROWS })
      .then((res) => {
        const map = Object.fromEntries(
          res.data.projects.map((p) => {
            const domain = projectMapper.fromResponse(p);
            return [domain.id, domain];
          })
        );
        dispatch(setProjects(map));
      })
      .catch(() => {
        dispatch(setError(intl.formatMessage(messages.loadError)));
      })
      .finally(() => {
        dispatch(setLoading(false));
      });
  }, [dispatch, intl]);

  /**
   * Handles tearsheet submission: creates the project (and optionally a flow),
   * updates the Redux store, then navigates to the canvas or project detail page.
   *
   * @param project - Validated project form values from {@link CreateProjectTearsheet}.
   * @param flow    - Optional flow values; if `flowName` is blank no flow is created.
   */
  const handleSubmit = async (
    project: CreateProjectFormValues,
    flow: { flowName: string; flowDescription: string; flowTags: string[] }
  ): Promise<void> => {
    try {
      const projectRes = await createProject(projectMapper.toCreateRequest(project));
      const created = projectMapper.fromResponse(projectRes.data);

      dispatch(setProject({ projectId: created.id, project: created }));

      if (flow.flowName.trim()) {
        const flowRes = await createFlow(
          flowMapper.toCreateRequest(
            { name: flow.flowName, description: flow.flowDescription, tags: flow.flowTags },
            created.id,
            buildFlowDefinition(flow.flowName, flow.flowDescription)
          )
        );
        const newFlowRow = flowMapper.fromResponse(flowRes.data);
        dispatch(setFlow({ flowId: newFlowRow.flow_id, flow: newFlowRow }));
        dispatch(setProject({ projectId: created.id, project: { ...created, flowCount: created.flowCount + 1 } }));
        go(navigate, generateRoute.canvas(newFlowRow.flow_id, created.id));
      } else {
        go(navigate, generateRoute.projectDetail(created.id));
      }
      notify.success(intl.formatMessage(messages.createSuccess, { name: project.name }));
    } catch {
      notify.error(intl.formatMessage(messages.createError));
      throw new Error('Failed to create project');
    }
  };

  // Sort by most recently modified first — the API may not guarantee order
  const rows = projects
    .slice()
    .sort((newer, older) => older.modifiedOn.localeCompare(newer.modifiedOn))
    .slice(0, MAX_ROWS);

  let cardChildren: React.ReactNode = null;

  if (loading) {
    cardChildren = <p className={cardStyles.itemLoading}>{intl.formatMessage(messages.loading)}</p>;
  } else if (error) {
    cardChildren = <p className={cardStyles.itemError}>{error}</p>;
  } else if (rows.length > 0) {
    cardChildren = (
      <div className={cardStyles.itemContainer}>
        <ul className={cardStyles.itemList}>
          {rows.map((project) => (
            <li key={project.id}>
              <Button
                kind="ghost"
                className={cardStyles.itemRow}
                onClick={() => { go(navigate, generateRoute.projectDetail(project.id)); }}
              >
                <span className={cardStyles.itemName}>{project.name}</span>
                <span className={cardStyles.itemMeta}>
                  {formatRelativeTime(project.modifiedOn)}
                </span>
              </Button>
            </li>
          ))}
        </ul>
        <Button
          kind="ghost"
          size="sm"
          className={cardStyles.viewAll}
          onClick={() => { go(navigate, ROUTES.PROJECTS); }}
        >
          {intl.formatMessage(messages.viewAll)}
        </Button>
      </div>
    );
  }

  return (
    <>
      <HomeCard
        title={intl.formatMessage(messages.title)}
        headerIcon={Add}
        headerIconDescription={intl.formatMessage(messages.createIconDescription)}
        onHeaderAction={() => { setTearsheetOpen(true); }}
        emptyTitle={intl.formatMessage(messages.emptyTitle)}
        emptySubtitle={intl.formatMessage(messages.emptySubtitle)}
        emptyAction={{
          text: intl.formatMessage(messages.emptyActionText),
          kind: 'tertiary',
          renderIcon: Add,
          onClick: () => { setTearsheetOpen(true); },
        }}
        wide
      >
        {cardChildren}
      </HomeCard>

      <CreateProjectTearsheet
        open={tearsheetOpen}
        onClose={() => { setTearsheetOpen(false); }}
        onSubmit={handleSubmit}
      />
    </>
  );
}
