import { defineMessages } from 'react-intl';

export const messages = defineMessages({
  noResultsTitle: {
    id: 'src.components.common.SharedDataTable.noResultsTitle',
    defaultMessage: 'No results found',
  },
  noResultsSubtitle: {
    id: 'src.components.common.SharedDataTable.noResultsSubtitle',
    defaultMessage: 'No features match "{searchValue}". Try a different search term.',
  },
  searchPlaceholder: {
    id: 'src.components.common.SharedDataTable.searchPlaceholder',
    defaultMessage: 'Search',
  },
});
