import { defineMessages } from 'react-intl';

export const messages = defineMessages({
  sleepSec: {
    id: 'src.components.PropertiesPanel.CustomPanels.Noop.sleepSec',
    defaultMessage: 'Sleep duration (seconds)',
  },
  sleepSecDescription: {
    id: 'src.components.PropertiesPanel.CustomPanels.Noop.sleepSecDescription',
    defaultMessage:
      'Seconds to sleep before passing data through. Use 0 for no delay. '
      + 'Values greater than 0 simulate slow operators for performance testing.',
  },
});
