/**
 * @fileoverview Custom hook that owns the background job-run poll loop.
 *
 * Lives in Canvas.tsx's directory because it is Canvas-specific: it dispatches
 * to the jobRun Redux slice and uses the job-run API actions.  The poll runs
 * in the Canvas component (not ReadOnlyCanvas) so it continues even when the
 * user navigates back to the edit canvas mid-run.
 *
 * Usage:
 *   const { startPoll, stopPoll } = useJobRunPoller();
 */

import { useCallback, useEffect, useRef } from 'react';
import { useIntl } from 'react-intl';
import { useAppDispatch } from '@/hooks';
import { useNotify } from '@/hooks/useNotify';
import { getJobRun } from '@/services/api/actions/job-run-actions';
import { setRunning, setExecutionLogs } from '@/slices/jobRunSlice';
import {
  COMPLETED_STATUSES,
  JOB_RUN_STATUS,
  POLL_INTERVAL_MS,
  POLL_FINAL_DELAY_MS,
  POLL_MAX_RETRIES,
} from '@/constants/jobRunStatus';
import { messages } from './useJobRunPoller.messages';

export interface UseJobRunPollerResult {
  /**
   * Start (or restart) a poll chain for the given jobRunId. Aborts any prior chain.
   * When `flowName` is provided, a notification is shown once the run reaches a
   * terminal status (success, warning or error). Omit it to poll silently.
   */
  startPoll: (jobRunId: string, flowName?: string) => void;
  /** Abort the current poll chain and clear all timers. */
  stopPoll: () => void;
}

export function useJobRunPoller(): UseJobRunPollerResult {
  const dispatch = useAppDispatch();
  const intl = useIntl();
  const notify = useNotify();

  const abortCtrlRef = useRef<AbortController>(new AbortController());
  const timerRef     = useRef<ReturnType<typeof setTimeout> | null>(null);
  const retryRef       = useRef(0);
  const networkRetryRef = useRef(0);  // counts consecutive network / 5xx retries
  const finalRef       = useRef(false);  // guards the one-shot 5 s final poll
  const jobRunIdRef    = useRef<string | null>(null);
  const flowNameRef    = useRef<string | null>(null);  // null = do not notify
  const notifiedRef    = useRef(false);  // guards the one-shot completion notification

  const notifyCompletion = useCallback((status: string): void => {
    const name = flowNameRef.current;
    if (!name || notifiedRef.current) { return; }
    if (status === JOB_RUN_STATUS.COMPLETED) {
      notifiedRef.current = true;
      notify.success(intl.formatMessage(messages.runCompleted, { name }));
    } else if (
      status === JOB_RUN_STATUS.COMPLETED_WITH_ERRORS ||
      status === JOB_RUN_STATUS.COMPLETED_WITH_WARNINGS
    ) {
      notifiedRef.current = true;
      notify.warning(intl.formatMessage(messages.runCompletedWithIssues, { name }));
    } else if (status === JOB_RUN_STATUS.FAILED) {
      notifiedRef.current = true;
      notify.error(intl.formatMessage(messages.runFailed, { name }));
    }
  }, [intl, notify]);

  // poll() is stable — reads jobRunId from ref, writes to Redux.
  const poll = useCallback(async (signal: AbortSignal): Promise<void> => {
    if (signal.aborted || !jobRunIdRef.current) { return; }
    try {
      const res = await getJobRun(jobRunIdRef.current, true, signal);
      if (signal.aborted) { return; }

      dispatch(setExecutionLogs(res.data));

      if (COMPLETED_STATUSES.has(res.data.job_stats.status)) {
        dispatch(setRunning(false));
        notifyCompletion(res.data.job_stats.status);
        // Fire ONE final poll after 5 s to capture backend-finalised data.
        if (!finalRef.current && !signal.aborted) {
          finalRef.current = true;
          timerRef.current = setTimeout(() => { void poll(signal); }, POLL_FINAL_DELAY_MS);
        }
        return;
      }

      if (!signal.aborted) {
        timerRef.current = setTimeout(() => { void poll(signal); }, POLL_INTERVAL_MS);
      }
    } catch (err: unknown) {
      if (signal.aborted) { return; }
      const httpStatus = (err as { response?: { status?: number } }).response?.status;

      // 404: job run not yet visible on the backend — retry up to POLL_MAX_RETRIES.
      if (httpStatus === 404 && retryRef.current < POLL_MAX_RETRIES) {
        retryRef.current += 1;
        timerRef.current = setTimeout(() => { void poll(signal); }, POLL_INTERVAL_MS);
        return;
      }

      // Network error (no httpStatus) or 5xx: transient — retry up to POLL_MAX_RETRIES
      // with the normal interval so a temporary backend blip doesn't hang the UI.
      if ((!httpStatus || httpStatus >= 500) && networkRetryRef.current < POLL_MAX_RETRIES) {
        networkRetryRef.current += 1;
        timerRef.current = setTimeout(() => { void poll(signal); }, POLL_INTERVAL_MS);
      }
      // 4xx (other than 404) or exhausted retries: stop polling — nothing we can do.
    }
  }, [dispatch, notifyCompletion]);

  const startPoll = useCallback((jobRunId: string, flowName?: string): void => {
    // Abort any previous chain so there is never more than one active.
    abortCtrlRef.current.abort();
    if (timerRef.current) { clearTimeout(timerRef.current); timerRef.current = null; }
    retryRef.current = 0;
    networkRetryRef.current = 0;
    finalRef.current = false;
    notifiedRef.current = false;
    flowNameRef.current = flowName ?? null;
    jobRunIdRef.current = jobRunId;
    const ac = new AbortController();
    abortCtrlRef.current = ac;
    dispatch(setRunning(true));
    // Defer by one tick — lets StrictMode cleanup abort mount1 before mount2 fires.
    timerRef.current = setTimeout(() => { void poll(ac.signal); }, 0);
  }, [dispatch, poll]);

  const stopPoll = useCallback((): void => {
    abortCtrlRef.current.abort();
    if (timerRef.current) { clearTimeout(timerRef.current); timerRef.current = null; }
    jobRunIdRef.current = null;
  }, []);

  // Cleanup on unmount — stop any in-flight poll when Canvas is destroyed.
  useEffect(() => () => { stopPoll(); }, [stopPoll]);

  return { startPoll, stopPoll };
}
