/**
 * @fileoverview Job run logs accordion component.
 * Displays one accordion item per node with log text, copy button, and "Show detailed log" link.
 *
 * Behaviour:
 *  - All accordion items open by default
 *  - Non-GUID nodeIds are skipped (e.g. error_logs key)
 *  - CopyButton per accordion item
 *  - Scroll to selected node via per-item ref map
 *  - Failed run with no node_sequence shows InlineNotification + job_stats.message
 */

import React, { useMemo, useEffect, useRef, useCallback } from 'react';
import { Accordion, AccordionItem, CopyButton, InlineNotification } from '@carbon/react';
import { useIntl } from 'react-intl';
import type { JobRunStatusResponse } from '@/types';
import { JOB_RUN_STATUS } from '@/constants/jobRunStatus';
import { LOG_SCROLL_DELAY_MS, LOG_PREVIEW_THRESHOLD } from '@/constants/runSidePanel';
import { messages } from './JobRunLogs.messages';
import styles from './JobRunLogs.module.scss';

interface JobRunLogsProps {
  executionLogs: JobRunStatusResponse;
  selectedNodeId: string | null;
  onShowFullLog: (log: string, title: string) => void;
}

const GUID_REGEX = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const isValidGuid = (str: string): boolean => GUID_REGEX.test(str);

export function JobRunLogs({
  executionLogs,
  selectedNodeId,
  onShowFullLog,
}: JobRunLogsProps): React.JSX.Element {
  const intl = useIntl();
  const { node_sequence, job_stats } = executionLogs;
  const isFailedNoSequence =
    (!node_sequence || node_sequence.length === 0) &&
    job_stats?.status?.toLowerCase() === JOB_RUN_STATUS.FAILED.toLowerCase();

  const nodeNameMap = useMemo(() => {
    const map: Record<string, string> = {};
    node_sequence?.forEach((nodeId) => {
      const nodeStat = job_stats.node_stats[nodeId];
      map[nodeId] = nodeStat ? nodeStat.name : nodeId;
    });
    return map;
  }, [node_sequence, job_stats.node_stats]);

  // Per-item ref map for reliable scroll-to-selected behaviour
  const itemRefs = useRef<Map<string, HTMLDivElement | null>>(new Map());
  const setItemRef = useCallback((nodeId: string, el: HTMLDivElement | null) => {
    if (el) { itemRefs.current.set(nodeId, el); }
    else { itemRefs.current.delete(nodeId); }
  }, []);

  // Auto-scroll to the selected node's accordion item
  useEffect(() => {
    if (!selectedNodeId) { return; }
    const timer = setTimeout(() => {
      const el = itemRefs.current.get(selectedNodeId);
      if (!el) { return; }
      // Scroll within the nearest [class*="tabContent"] ancestor
      const scrollContainer = el.closest('[class*="tabContent"]');
      if (scrollContainer) {
        const elRect = el.getBoundingClientRect();
        const containerRect = scrollContainer.getBoundingClientRect();
        const isAbove = elRect.top < containerRect.top;
        const isBelow = elRect.bottom > containerRect.bottom;
        if (isAbove || isBelow) {
          const targetScroll =
            scrollContainer.scrollTop + (elRect.top - containerRect.top) - 20;
          scrollContainer.scrollTo({ top: targetScroll, behavior: 'smooth' });
        }
      }
    }, LOG_SCROLL_DELAY_MS);
    return () => { clearTimeout(timer); };
  }, [selectedNodeId, executionLogs]);

  // Failed run with no per-node logs — show error notification + job_stats.message
  if (isFailedNoSequence) {
    return (
      <div className={styles.logsContainer}>
        <InlineNotification
          kind="error"
          title={intl.formatMessage(messages.errorTitle)}
          subtitle={intl.formatMessage(messages.errorSubtitle)}
          lowContrast
          hideCloseButton
          className={styles.inlineNotification}
        />
        {job_stats?.message && (
          <div className={styles.flowLogs}>
            <div className={styles.logRow}>
              <div className={styles.displayedLogContent}>{job_stats.message}</div>
            </div>
          </div>
        )}
      </div>
    );
  }

  return (
    <div className={styles.logsContainer}>
      <Accordion>
        {node_sequence?.map((nodeId) => {
          // Skip non-GUID keys (e.g. "error_logs", "job_stats") — only actual node IDs are GUIDs
          if (!isValidGuid(nodeId)) { return null; }

          const logText = (executionLogs as Record<string, unknown>)[nodeId];
          const fullLog = logText ? String(logText) : '';
          const nodeName = nodeNameMap[nodeId] ?? nodeId;
          const isTruncated = fullLog.length > LOG_PREVIEW_THRESHOLD;
          const displayedLog = isTruncated
            ? `${fullLog.slice(0, LOG_PREVIEW_THRESHOLD)}...`
            : fullLog;

          return (
            <div
              key={nodeId}
              ref={(el) => { setItemRef(nodeId, el); }}
            >
              <AccordionItem
                title={nodeName}
                open  // all items open by default
              >
                <div className={styles.logContent}>
                  <div className={styles.logRow}>
                    <div className={styles.displayedLogContent}>{displayedLog}</div>
                    <CopyButton
                      onClick={() => { void navigator.clipboard.writeText(fullLog).catch(() => {}); }}
                      autoAlign
                    />
                  </div>
                  {isTruncated && (
                    <div className={styles.showMoreLink}>
                      <button
                          type="button"
                          className={styles.showMoreButton}
                          onClick={() => {
                            onShowFullLog(fullLog, nodeName);
                          }}
                        >
                          {intl.formatMessage(messages.showDetailedLog)}
                        </button>
                    </div>
                  )}
                </div>
              </AccordionItem>
            </div>
          );
        })}
      </Accordion>
    </div>
  );
}
