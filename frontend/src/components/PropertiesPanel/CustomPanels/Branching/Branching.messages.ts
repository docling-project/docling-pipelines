import { defineMessages } from 'react-intl';

export const messages = defineMessages({
  targetNode: {
    id: 'src.components.PropertiesPanel.CustomPanels.Branching.targetNode',
    defaultMessage: 'Target Node',
  },
  linkName: {
    id: 'src.components.PropertiesPanel.CustomPanels.Branching.linkName',
    defaultMessage: 'Link Name',
  },
  emptyState: {
    id: 'src.components.PropertiesPanel.CustomPanels.Branching.emptyState',
    defaultMessage: 'Connect output links from this node and set a condition on each link to define branching logic.',
  },
  helperText: {
    id: 'src.components.PropertiesPanel.CustomPanels.Branching.helperText',
    defaultMessage:
      'Each row corresponds to one output link. '
      + 'To edit a link name or condition, right-click the link on the canvas.',
  },
});
