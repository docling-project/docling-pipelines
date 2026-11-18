import { defineMessages } from 'react-intl';

export const messages = defineMessages({
  ariaLabel: {
    id: 'src.components.Canvas.NodeSuggestion.ariaLabel',
    defaultMessage: 'Recommended next nodes',
  },
  title: {
    id: 'src.components.Canvas.NodeSuggestion.title',
    defaultMessage: 'Recommended next nodes',
  },
  subtitle: {
    id: 'src.components.Canvas.NodeSuggestion.subtitle',
    defaultMessage: 'Choose a recommended node to continue, or add other nodes from the palette.',
  },
  closeDescription: {
    id: 'src.components.Canvas.NodeSuggestion.closeDescription',
    defaultMessage: 'Close',
  },
  searchPlaceholder: {
    id: 'src.components.Canvas.NodeSuggestion.searchPlaceholder',
    defaultMessage: 'Find nodes',
  },
  noMatchingNodes: {
    id: 'src.components.Canvas.NodeSuggestion.noMatchingNodes',
    defaultMessage: 'No matching nodes',
  },
  noSuggestionsAvailable: {
    id: 'src.components.Canvas.NodeSuggestion.noSuggestionsAvailable',
    defaultMessage: 'No suggestions available',
  },
});
