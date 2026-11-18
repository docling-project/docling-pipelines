import { defineMessages } from 'react-intl';

export const messages = defineMessages({
  addButton: {
    id: 'src.components.common.ListInput.addButton',
    defaultMessage: 'Add',
  },
  removeItem: {
    id: 'src.components.common.ListInput.removeItem',
    defaultMessage: 'Remove',
  },
  duplicateValue: {
    id: 'src.components.common.ListInput.duplicateValue',
    defaultMessage: '"{value}" has already been added.',
  },
  itemsPerPage: {
    id: 'src.components.common.ListInput.itemsPerPage',
    defaultMessage: 'Items per page:',
  },
  previousPage: {
    id: 'src.components.common.ListInput.previousPage',
    defaultMessage: 'Previous page',
  },
  nextPage: {
    id: 'src.components.common.ListInput.nextPage',
    defaultMessage: 'Next page',
  },
  itemRange: {
    id: 'src.components.common.ListInput.itemRange',
    defaultMessage: '{min}-{max} of {total} items',
  },
  pageRange: {
    id: 'src.components.common.ListInput.pageRange',
    defaultMessage: '{current} of {total} pages',
  },
});
