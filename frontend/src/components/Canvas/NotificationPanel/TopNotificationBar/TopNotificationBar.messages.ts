import { defineMessages } from 'react-intl';

export const messages = defineMessages({
  validationWarningTitle: {
    id: 'src.components.Canvas.NotificationPanel.TopNotificationBar.validationWarningTitle',
    defaultMessage: 'Validation warning',
  },
  validationFailedTitle: {
    id: 'src.components.Canvas.NotificationPanel.TopNotificationBar.validationFailedTitle',
    defaultMessage: 'Validation failed',
  },
  errorSingular: {
    id: 'src.components.Canvas.NotificationPanel.TopNotificationBar.errorSingular',
    defaultMessage: '1 validation error',
  },
  errorPlural: {
    id: 'src.components.Canvas.NotificationPanel.TopNotificationBar.errorPlural',
    defaultMessage: '{count} validation errors',
  },
  warningSingular: {
    id: 'src.components.Canvas.NotificationPanel.TopNotificationBar.warningSingular',
    defaultMessage: '1 warning',
  },
  warningPlural: {
    id: 'src.components.Canvas.NotificationPanel.TopNotificationBar.warningPlural',
    defaultMessage: '{count} warnings',
  },
  messageSingularIs: {
    id: 'src.components.Canvas.NotificationPanel.TopNotificationBar.messageSingularIs',
    defaultMessage: 'there is {parts}',
  },
  messagePluralAre: {
    id: 'src.components.Canvas.NotificationPanel.TopNotificationBar.messagePluralAre',
    defaultMessage: 'there are {parts}',
  },
  view: {
    id: 'src.components.Canvas.NotificationPanel.TopNotificationBar.view',
    defaultMessage: 'View',
  },
  closeNotification: {
    id: 'src.components.Canvas.NotificationPanel.TopNotificationBar.closeNotification',
    defaultMessage: 'Close notification',
  },
});
