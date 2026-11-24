import { defineMessages } from 'react-intl';

export const messages = defineMessages({
  checkingAuth: {
    id: 'src.components.common.ProtectedRoute.checkingAuth',
    defaultMessage: 'Checking authentication...',
  },
  authUnavailableTitle: {
    id: 'src.components.common.ProtectedRoute.authUnavailableTitle',
    defaultMessage: 'Authentication service unavailable',
  },
  authUnavailableSubtitle: {
    id: 'src.components.common.ProtectedRoute.authUnavailableSubtitle',
    defaultMessage: 'Could not verify your session. Please try again.',
  },
  retry: {
    id: 'src.components.common.ProtectedRoute.retry',
    defaultMessage: 'Retry',
  },
});
