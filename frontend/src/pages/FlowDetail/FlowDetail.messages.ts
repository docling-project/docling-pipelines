import { defineMessages } from 'react-intl';

export const messages = defineMessages({
  flowNotFound: {
    id: 'src.pages.FlowDetail.flowNotFound',
    defaultMessage: 'Flow not found.',
  },
  flowLoadError: {
    id: 'src.pages.FlowDetail.flowLoadError',
    defaultMessage: 'Failed to load flow. Please try again.',
  },
  runsLoadError: {
    id: 'src.pages.FlowDetail.runsLoadError',
    defaultMessage: 'Failed to load runs. Please try again.',
  },
  aboutFlow: {
    id: 'src.pages.FlowDetail.aboutFlow',
    defaultMessage: 'About flow',
  },
  deleteRunSuccess: {
    id: 'src.pages.FlowDetail.deleteRunSuccess',
    defaultMessage: 'Run {id} deleted successfully.',
  },
  deleteRunError: {
    id: 'src.pages.FlowDetail.deleteRunError',
    defaultMessage: 'Failed to delete run',
  },
  deleteRunErrorSubtitle: {
    id: 'src.pages.FlowDetail.deleteRunErrorSubtitle',
    defaultMessage: 'Could not delete run. Please try again.',
  },
  loading: {
    id: 'src.pages.FlowDetail.loading',
    defaultMessage: 'Loading flow...',
  },
  runsTitle: {
    id: 'src.pages.FlowDetail.runsTitle',
    defaultMessage: '{name} runs',
  },
  viewFlow: {
    id: 'src.pages.FlowDetail.viewFlow',
    defaultMessage: 'View flow',
  },
  runsErrorTitle: {
    id: 'src.pages.FlowDetail.runsErrorTitle',
    defaultMessage: 'Failed to load runs',
  },
  tryAgain: {
    id: 'src.pages.FlowDetail.tryAgain',
    defaultMessage: 'Try again',
  },
  emptyTitle: {
    id: 'src.pages.FlowDetail.emptyTitle',
    defaultMessage: 'No runs yet',
  },
  emptySubtitle: {
    id: 'src.pages.FlowDetail.emptySubtitle',
    defaultMessage: 'Run this flow from the canvas to see execution history here.',
  },
  editModalTitle: {
    id: 'src.pages.FlowDetail.editModalTitle',
    defaultMessage: 'Edit flow details',
  },
  deleteAssetType: {
    id: 'src.pages.FlowDetail.deleteAssetType',
    defaultMessage: 'Run',
  },
});
