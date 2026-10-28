import { defineMessages } from 'react-intl';

export const messages = defineMessages({
  title: {
    id: 'src.components.PropertiesPanel.CustomPanels.Ededup.title',
    defaultMessage: 'No configuration required',
  },
  subtitle: {
    id: 'src.components.PropertiesPanel.CustomPanels.Ededup.subtitle',
    defaultMessage:
      'This operator automatically removes exact duplicate documents based on a content hash. '
      + 'No parameters need to be set.',
  },
});
