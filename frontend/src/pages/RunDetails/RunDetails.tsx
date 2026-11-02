/**
 * @fileoverview Flow run details page — `/flows/:flow_id/runs/:run_id`.
 *
 * Renders the ReadOnlyCanvas for a specific job run.
 * Can be reached from:
 *   1. FlowDetail "View run" overflow menu item (history)
 *   2. Canvas "Run" button after a new run is created (navigates here)
 *   3. Canvas "View run" button while a run is in progress (navigates here)
 *
 * Back button returns to FlowDetail (`/flows/:flow_id?project_id=…`).
 */

import React, { useEffect, useState } from 'react';
import { useIntl } from 'react-intl';
import { useParams, useSearchParams, useNavigate } from 'react-router-dom';
import { InlineLoading, InlineNotification } from '@carbon/react';
import type { PipelineFlowDef } from '@elyra/canvas';
import { ReadOnlyCanvas } from '@/components';
import { getJobRun, cancelJobRun, getJobRunFlowDefinition } from '@/services/api/actions/job-run-actions';
import { log4js, logUtil } from '@/utils/logger';
import { useAppDispatch, useJobRunPoller } from '@/hooks';
import {
  setCurrentRun,
  setRunning,
  setExecutionLogs,
} from '@/slices/jobRunSlice';
import { generateRoute } from '@/config';
import { messages } from './RunDetails.messages';
import styles from './RunDetails.module.scss';

const logger = log4js.getLogger('RunDetails');

export function RunDetails(): React.JSX.Element {
  const intl = useIntl();
  const { flow_id: flowId, run_id: runId } = useParams<{ flow_id: string; run_id: string }>();
  const [searchParams] = useSearchParams();
  const projectId = searchParams.get('project_id') ?? '';
  const navigate = useNavigate();
  const dispatch = useAppDispatch();
  const { startPoll, stopPoll } = useJobRunPoller();

  // Local state for the fetched pipeline flow definition
  const [pipelineFlow, setPipelineFlow] = useState<PipelineFlowDef | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  // ── Bootstrap ─────────────────────────────────────────────────────────────
  // Fetch the flow definition and arm the Redux run-viewer on mount.
  // We must set currentRun + start polling so ReadOnlyCanvas has IDs to work with.
  useEffect(() => {
    if (!flowId || !runId) { return; }

    let cancelled = false;

    const bootstrap = async (): Promise<void> => {
      try {
        // Fetch the flow definition as it was when this run was executed.
        // This ensures the canvas shows exactly what ran, not the current
        // (potentially modified) live definition.
        const snapshotRes = await getJobRunFlowDefinition(runId);
        if (cancelled) { return; }
        const definition = snapshotRes.data as unknown as PipelineFlowDef | undefined;
        if (!definition) {
          setLoadError(intl.formatMessage(messages.definitionUnavailable));
          return;
        }
        setPipelineFlow(definition);

        // Check if the run is already complete or still in-progress
        const runRes = await getJobRun(runId, false);
        if (cancelled) { return; }

        // Clear any stale logs from a previous viewer session
        dispatch(setExecutionLogs(null));
        dispatch(setCurrentRun({ jobId: flowId, jobRunId: runId }));

        // Arm the poller — it will start immediately and dispatch setRunning(true)
        startPoll(runId);

        // If the run returned a terminal status on the first fetch, the poller's
        // first response will dispatch setRunning(false) on its own. But we set
        // the initial executionLogs so the viewer renders immediately.
        dispatch(setExecutionLogs(runRes.data));
      } catch {
        if (!cancelled) {
          setLoadError(intl.formatMessage(messages.loadError));
        }
      }
    };

    void bootstrap();

    return () => {
      cancelled = true;
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps -- intentionally run once on mount
  }, [flowId, runId]);

  // ── Cleanup on unmount ────────────────────────────────────────────────────
  useEffect(() =>
     () => {
      stopPoll();
      dispatch(setCurrentRun(null));
      dispatch(setExecutionLogs(null));
      dispatch(setRunning(false));
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps -- run only on unmount
  , []);

  // ── Navigation handlers ───────────────────────────────────────────────────

  const handleExit = (): void => {
    // Always go back to the flow detail (run history) page
    if (flowId) {
      void navigate(generateRoute.flowDetail(flowId, projectId));
    }
  };

  const handleRunAgain = (newJobRunId: string): void => {
    if (!flowId) { return; }
    dispatch(setRunning(true));
    dispatch(setCurrentRun({ jobId: flowId, jobRunId: newJobRunId }));
    startPoll(newJobRunId);
    // Navigate to the new run's URL so the URL always reflects what's shown
    void navigate(generateRoute.runDetails(flowId, newJobRunId, projectId), { replace: true });
  };

  const handleStop = (): void => {
    if (!runId) { return; }
    stopPoll();
    void cancelJobRun(runId)
      .catch((err: unknown) => {
        logUtil.error({ logger, message: 'Failed to cancel job run', data: err });
      })
      .finally(() => {
        startPoll(runId);
      });
  };

  // ── Loading / error guards ────────────────────────────────────────────────

  if (loadError) {
    return (
      <div className={styles.stateContainer}>
        <InlineNotification
          kind="error"
          title={intl.formatMessage(messages.errorTitle)}
          subtitle={loadError}
          hideCloseButton
        />
      </div>
    );
  }

  // pipelineFlow is the only local state we wait on — flowId and runId come from
  // the URL params and are stable. currentJobRunId / currentJobId mirror flowId /
  // runId after bootstrap so checking them separately is redundant.
  if (!pipelineFlow || !flowId || !runId) {
    return (
      <div className={styles.stateContainer}>
        <InlineLoading description={intl.formatMessage(messages.loading)} />
      </div>
    );
  }

  return (
    <div className={styles.runDetailsPage}>
      <ReadOnlyCanvas
        key={runId}
        pipelineFlow={pipelineFlow}
        jobId={flowId}
        jobRunId={runId}
        onExit={handleExit}
        onRunAgain={handleRunAgain}
        onStop={handleStop}
      />
    </div>
  );
}
