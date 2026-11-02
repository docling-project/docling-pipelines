/**
 * @fileoverview Right side panel for the pipeline run viewer showing job run logs and node details.
 * Contains two tabs: Log Details (accordion of node logs) and Node Summary (node metadata).
 *
 * Behaviour:
 *  - Log Details tab is disabled when there is no node_sequence
 *  - Node Summary tab is hidden for failed runs with an empty node_sequence
 *  - "Show detailed log" modal includes a CopyButton for one-click clipboard copy
 */

import React, { useState, useCallback } from 'react';
import { CopyButton } from '@carbon/react';
import { Close, Download } from '@carbon/icons-react';
import { useIntl } from 'react-intl';
import type { JobRunStatusResponse } from '@/types';
import { JOB_RUN_STATUS } from '@/constants/jobRunStatus';
import {
  LOG_DOWNLOAD_MIME_TYPE,
  LOG_DOWNLOAD_FILENAME_PREFIX,
  LOG_SECTION_SEPARATOR,
} from '@/constants/runSidePanel';
import { JobRunLogs } from './JobRunLogs';
import { NodeSummary } from './NodeSummary';
import { messages } from './RunSidePanel.messages';
import styles from './RunSidePanel.module.scss';

interface RunSidePanelProps {
  executionLogs: JobRunStatusResponse;
  selectedNodeId: string | null;
  activeTabIndex: number;
  onTabChange: (idx: number) => void;
  onClose: () => void;
}

export function RunSidePanel({
  executionLogs,
  selectedNodeId,
  activeTabIndex,
  onTabChange,
  onClose,
}: RunSidePanelProps): React.JSX.Element {
  const intl = useIntl();
  const [showFullLog, setShowFullLog] = useState<string | null>(null);
  const [showFullLogTitle, setShowFullLogTitle] = useState<string | null>(null);

  const { node_sequence, job_stats } = executionLogs;

  // Log Details tab is disabled when there are no per-node logs
  const hasNodeSequence = node_sequence && node_sequence.length > 0;
  const isFailedNoSequence =
    !hasNodeSequence && job_stats?.status?.toLowerCase() === JOB_RUN_STATUS.FAILED.toLowerCase();

  // Node Summary tab hidden for failed runs that have no per-node sequence
  const showNodeSummaryTab = !isFailedNoSequence;

  const selectedNodeMetadata = selectedNodeId
    ? executionLogs.node_metadata.find((m) => m.id === selectedNodeId)
    : null;

  const handleDownloadLogs = useCallback(() => {
    const logsContent = (node_sequence ?? [])
      .map((nodeId) => {
        const logText = (executionLogs as Record<string, unknown>)[nodeId];
        const nodeStat = job_stats.node_stats[nodeId];
        const name = nodeStat ? nodeStat.name : nodeId;
        return `${LOG_SECTION_SEPARATOR(name)}${logText ? String(logText) : '[No logs]'}`;
      })
      .join('\n');

    const blob = new Blob([logsContent], { type: LOG_DOWNLOAD_MIME_TYPE });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `${LOG_DOWNLOAD_FILENAME_PREFIX}${job_stats.job_run_id}.txt`;
    link.click();
    URL.revokeObjectURL(url);
  }, [node_sequence, job_stats, executionLogs]);

  const handleShowFullLog = useCallback((log: string, title: string) => {
    setShowFullLog(log);
    setShowFullLogTitle(title);
  }, []);

  const handleCloseModal = useCallback(() => {
    setShowFullLog(null);
    setShowFullLogTitle(null);
  }, []);

  return (
    <div className={styles.tabsContainer}>
      {/* Sticky header: tab buttons + download + close */}
      <div className={styles.panelHeader}>
        <div className={styles.tabList}>
          <button
            className={`${styles.tabButton} ${activeTabIndex === 0 ? styles.activeTab : ''}`}
            onClick={() => { onTabChange(0); }}
            disabled={!hasNodeSequence && !isFailedNoSequence}
          >
            {intl.formatMessage(messages.tabLogDetails)}
          </button>
          {showNodeSummaryTab && (
            <button
              className={`${styles.tabButton} ${activeTabIndex === 1 ? styles.activeTab : ''}`}
              onClick={() => { onTabChange(1); }}
            >
              {intl.formatMessage(messages.tabNodeSummary)}
            </button>
          )}
        </div>
        {activeTabIndex === 0 && (
          <button className={styles.iconButtonWrapper} onClick={handleDownloadLogs} title={intl.formatMessage(messages.downloadLogs)}>
            <Download size={16} />
          </button>
        )}
        <button className={styles.closeButton} onClick={onClose} title={intl.formatMessage(messages.close)}>
          <Close size={20} />
        </button>
      </div>

      {/* Tab content */}
      <div className={styles.tabContent}>
        {activeTabIndex === 0 && (
          <JobRunLogs
            executionLogs={executionLogs}
            selectedNodeId={selectedNodeId}
            onShowFullLog={handleShowFullLog}
          />
        )}

        {activeTabIndex === 1 && (
          selectedNodeMetadata ? (
            <NodeSummary
              nodeMetadata={selectedNodeMetadata}
              jobStats={executionLogs.job_stats}
            />
          ) : (
            <div className={styles.emptyTabContent}>
              <p>{intl.formatMessage(messages.nodeSummaryEmpty)}</p>
            </div>
          )
        )}
      </div>

      {/* "Show detailed log" modal with CopyButton for one-click clipboard copy */}
      {showFullLog && (
        <div className={styles.fullLogModal}>
          <div className={styles.fullLogContent}>
            <div className={styles.fullLogHeader}>
              <h4>{showFullLogTitle}</h4>
              <div className={styles.fullLogHeaderActions}>
                <CopyButton
                  onClick={() => {
                    void navigator.clipboard.writeText(showFullLog ?? '').catch(() => {});
                  }}
                />
                <button
                  className={styles.closeButton}
                  onClick={handleCloseModal}
                  title={intl.formatMessage(messages.close)}
                >
                  <Close size={20} />
                </button>
              </div>
            </div>
            <pre className={styles.fullLogText}>{showFullLog}</pre>
          </div>
        </div>
      )}
    </div>
  );
}
