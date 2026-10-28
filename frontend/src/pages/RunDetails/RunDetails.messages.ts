import { defineMessages } from 'react-intl';

export const messages = defineMessages({
  definitionUnavailable: {
    id: 'src.pages.RunDetails.definitionUnavailable',
    defaultMessage: 'Flow definition not available for this run.',
  },
  loadError: {
    id: 'src.pages.RunDetails.loadError',
    defaultMessage: 'Failed to load run details. Please try again.',
  },
  errorTitle: {
    id: 'src.pages.RunDetails.errorTitle',
    defaultMessage: 'Error',
  },
  loading: {
    id: 'src.pages.RunDetails.loading',
    defaultMessage: 'Loading run...',
  },
});
