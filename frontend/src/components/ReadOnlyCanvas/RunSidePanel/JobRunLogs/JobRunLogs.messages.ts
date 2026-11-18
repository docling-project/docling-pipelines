import { defineMessages } from 'react-intl';

export const messages = defineMessages({
  errorTitle: {
    id: 'src.components.ReadOnlyCanvas.RunSidePanel.JobRunLogs.errorTitle',
    defaultMessage: 'Run job failed',
  },
  errorSubtitle: {
    id: 'src.components.ReadOnlyCanvas.RunSidePanel.JobRunLogs.errorSubtitle',
    defaultMessage: 'Check your configuration and try again',
  },
  showDetailedLog: {
    id: 'src.components.ReadOnlyCanvas.RunSidePanel.JobRunLogs.showDetailedLog',
    defaultMessage: 'Show detailed log',
  },
  copyToClipboard: {
    id: 'src.components.ReadOnlyCanvas.RunSidePanel.JobRunLogs.copyToClipboard',
    defaultMessage: 'Copy to clipboard',
  },
  copied: {
    id: 'src.components.ReadOnlyCanvas.RunSidePanel.JobRunLogs.copied',
    defaultMessage: 'Copied',
  },
});
