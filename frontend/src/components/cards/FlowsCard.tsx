import React, { useCallback, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useIntl } from 'react-intl';
import { Button } from '@carbon/react';
import { Renew } from '@carbon/icons-react';
import { ROUTES, generateRoute } from '@/config';
import { go } from '@/utils';
import { useAppDispatch, useAppSelector } from '@/hooks';
import { getFlows } from '@/services/api';
import * as flowMapper from '@/services/api/mappers/flow-mapper';
import { setFlows, setLoading, setError } from '@/slices/flowSlice';
import { selectFlowsArray, selectFlowLoading, selectFlowError } from '@/selectors';
import { formatRelativeTime } from '@/utils/formatRelativeTime';
import { HomeCard } from '../HomeCard';
import cardStyles from '../HomeCard/HomeCard.module.scss';
import { messages } from './FlowsCard.messages';

const MAX_ROWS = 5;

/**
 * Home page card showing the 5 most recently modified flows.
 *
 * - Fetches flows on mount via `GET /api/flows?limit=5` (BFF adds `is_elyra=true`).
 * - The refresh icon in the card header re-fetches without navigating.
 * - Flows created via {@link ProjectsCard} appear immediately because the Redux
 *   store is updated via `setFlow` and `selectFlowsArray` is reactive.
 * - Sorted client-side by `modified_on` (ISO 8601, descending); empty strings last.
 * - Renders an empty state when there are no flows yet.
 */
export function FlowsCard(): React.JSX.Element {
  const navigate = useNavigate();
  const dispatch = useAppDispatch();
  const intl = useIntl();

  const flows = useAppSelector(selectFlowsArray);
  const loading = useAppSelector(selectFlowLoading);
  const error = useAppSelector(selectFlowError);

  const fetchFlows = useCallback((): void => {
    dispatch(setLoading(true));
    getFlows({ limit: MAX_ROWS })
      .then((res) => {
        const map = Object.fromEntries(
          res.data.flows.map((f) => {
            const row = flowMapper.fromResponse(f);
            return [row.flow_id, row];
          })
        );
        dispatch(setFlows(map));
      })
      .catch(() => {
        dispatch(setError(intl.formatMessage(messages.loadError)));
      })
      .finally(() => {
        dispatch(setLoading(false));
      });
  }, [dispatch, intl]);

  // Fetch on mount
  useEffect(() => {
    fetchFlows();
  }, [fetchFlows]);

  // Sort by most recently modified first.
  // Flows added via ProjectsCard.handleSubmit land in the store immediately via
  // setFlow — they appear here without a refresh because selectFlowsArray is reactive.
  const rows = flows
    .slice()
    .sort((newer, older) => {
      // ISO strings sort lexicographically correctly; empty strings sort last
      if (!newer.modified_on) { return 1; }
      if (!older.modified_on) { return -1; }
      return older.modified_on.localeCompare(newer.modified_on);
    })
    .slice(0, MAX_ROWS);

  let cardChildren: React.ReactNode = null;

  if (loading) {
    cardChildren = <p className={cardStyles.itemLoading}>{intl.formatMessage(messages.loading)}</p>;
  } else if (error) {
    cardChildren = <p className={cardStyles.itemError}>{error}</p>;
  } else if (rows.length > 0) {
    cardChildren = (
      <ul className={cardStyles.itemList}>
        {rows.map((flow) => (
          <li key={flow.flow_id}>
            <Button
              kind="ghost"
              className={cardStyles.itemRow}
              onClick={() => {
                go(navigate,
                  flow.project_id
                    ? generateRoute.flowDetail(flow.flow_id, flow.project_id)
                    : ROUTES.PROJECTS
                );
              }}
            >
              <span className={cardStyles.itemName}>{flow.name}</span>
              <span className={cardStyles.itemMeta}>
                {formatRelativeTime(flow.modified_on)}
              </span>
            </Button>
          </li>
        ))}
      </ul>
    );
  }

  return (
    <HomeCard
      title={intl.formatMessage(messages.title)}
      headerIcon={Renew}
      headerIconDescription={intl.formatMessage(messages.refreshDescription)}
      onHeaderAction={fetchFlows}
      emptyTitle={intl.formatMessage(messages.emptyTitle)}
      emptySubtitle={intl.formatMessage(messages.emptySubtitle)}
    >
      {cardChildren}
    </HomeCard>
  );
}
