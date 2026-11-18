import { defineMessages } from 'react-intl';

export const messages = defineMessages({
  title: {
    id: 'src.components.Canvas.FlowRunHistoryTearsheet.title',
    defaultMessage: 'Flow run history',
  },
  headerTimestamp: {
    id: 'src.components.Canvas.FlowRunHistoryTearsheet.headerTimestamp',
    defaultMessage: 'Timestamp',
  },
  headerStatus: {
    id: 'src.components.Canvas.FlowRunHistoryTearsheet.headerStatus',
    defaultMessage: 'Status',
  },
  headerDuration: {
    id: 'src.components.Canvas.FlowRunHistoryTearsheet.headerDuration',
    defaultMessage: 'Duration',
  },
  headerLogs: {
    id: 'src.components.Canvas.FlowRunHistoryTearsheet.headerLogs',
    defaultMessage: 'Logs',
  },
  emptyTitle: {
    id: 'src.components.Canvas.FlowRunHistoryTearsheet.emptyTitle',
    defaultMessage: 'No runs yet',
  },
  emptySubtitle: {
    id: 'src.components.Canvas.FlowRunHistoryTearsheet.emptySubtitle',
    defaultMessage: 'Run this flow to see execution history here.',
  },
  downloadLogsDescription: {
    id: 'src.components.Canvas.FlowRunHistoryTearsheet.downloadLogsDescription',
    defaultMessage: 'Download logs',
  },
  statusCompleted: {
    id: 'src.components.Canvas.FlowRunHistoryTearsheet.statusCompleted',
    defaultMessage: 'Completed',
  },
  statusInProgress: {
    id: 'src.components.Canvas.FlowRunHistoryTearsheet.statusInProgress',
    defaultMessage: 'In progress',
  },
  statusRunWithIssues: {
    id: 'src.components.Canvas.FlowRunHistoryTearsheet.statusRunWithIssues',
    defaultMessage: 'Run with issues',
  },
  statusFailed: {
    id: 'src.components.Canvas.FlowRunHistoryTearsheet.statusFailed',
    defaultMessage: 'Failed',
  },
  statusCanceled: {
    id: 'src.components.Canvas.FlowRunHistoryTearsheet.statusCanceled',
    defaultMessage: 'Canceled',
  },
  statusCompletedWithErrors: {
    id: 'src.components.Canvas.FlowRunHistoryTearsheet.statusCompletedWithErrors',
    defaultMessage: 'Completed with errors',
  },
  statusCompletedWithWarnings: {
    id: 'src.components.Canvas.FlowRunHistoryTearsheet.statusCompletedWithWarnings',
    defaultMessage: 'Completed with warnings',
  },
});
