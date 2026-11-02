import { defineMessages } from 'react-intl';

export const messages = defineMessages({
  title: {
    id: 'src.components.common.DeleteModal.title',
    defaultMessage: 'Delete {assetType}',
  },
  body: {
    id: 'src.components.common.DeleteModal.body',
    defaultMessage: 'You are going to delete {assetName} permanently. This action can\'t be undone.',
  },
  cancel: {
    id: 'src.components.common.DeleteModal.cancel',
    defaultMessage: 'Cancel',
  },
  delete: {
    id: 'src.components.common.DeleteModal.delete',
    defaultMessage: 'Delete',
  },
  deleting: {
    id: 'src.components.common.DeleteModal.deleting',
    defaultMessage: 'Deleting...',
  },
});
