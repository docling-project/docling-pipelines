import { useEffect, useMemo, useState } from 'react';
import { getFlowsByProjectId } from '@/services/api';
import type { Flow } from '@/types';
import { selectFlowsArray } from '@/selectors';
import { useAppSelector } from './useAppSelector';

interface UseSiblingFlowNamesOptions {
  /** Project whose flows are compared against. When empty, no names are returned. */
  readonly projectId: string | null | undefined;
  /** Flow being edited; excluded so saving without a rename is never a duplicate. */
  readonly flowId: string | null | undefined;
  /** Fetch from the backend only while true (e.g. while the edit modal is open). */
  readonly enabled: boolean;
}

/**
 * Names of the other flows in a project, for duplicate detection on blur in the
 * edit-flow modal.
 *
 * The Redux flow map only holds the flows the user has already loaded - on a deep
 * link or refresh it may contain just the current flow, which made the duplicate
 * error appear only after Save (via the 409 fallback). While `enabled`, the full
 * project list is fetched so the check works as soon as the name field loses focus.
 * Store names are merged in so a failed fetch degrades to the previous behaviour.
 */
export function useSiblingFlowNames({ projectId, flowId, enabled }: UseSiblingFlowNamesOptions): string[] {
  const storeFlows = useAppSelector(selectFlowsArray);
  const [fetched, setFetched] = useState<Flow[]>([]);

  useEffect(() => {
    if (!enabled || !projectId) { return; }
    let cancelled = false;
    getFlowsByProjectId(projectId)
      .then((res) => {
        if (!cancelled) { setFetched(res.data.flows); }
      })
      .catch(() => {
        // Non-fatal: fall back to the names already in the store.
      });
    return () => { cancelled = true; };
  }, [enabled, projectId]);

  return useMemo(() => {
    if (!projectId) { return []; }
    const names = new Map<string, string>();
    for (const f of storeFlows) {
      if (f.project_id === projectId && f.flow_id !== flowId) { names.set(f.name.trim().toLowerCase(), f.name); }
    }
    for (const f of fetched) {
      if (f.flow_id !== flowId && f.name) { names.set(f.name.trim().toLowerCase(), f.name); }
    }
    return [...names.values()];
  }, [storeFlows, fetched, projectId, flowId]);
}
