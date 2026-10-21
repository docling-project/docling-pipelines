import { defineMessages } from 'react-intl';

export const messages = defineMessages({
  errorTitle: {
    id: 'src.components.common.EditDetailsModal.errorTitle',
    defaultMessage: 'Failed to save',
  },
  nameLabel: {
    id: 'src.components.common.EditDetailsModal.nameLabel',
    defaultMessage: 'Name',
  },
  nameRequired: {
    id: 'src.components.common.EditDetailsModal.nameRequired',
    defaultMessage: 'Name is required',
  },
  descriptionLabel: {
    id: 'src.components.common.EditDetailsModal.descriptionLabel',
    defaultMessage: 'Description (optional)',
  },
  tagsLabel: {
    id: 'src.components.common.EditDetailsModal.tagsLabel',
    defaultMessage: 'Add tags (optional)',
  },
  cancel: {
    id: 'src.components.common.EditDetailsModal.cancel',
    defaultMessage: 'Cancel',
  },
  save: {
    id: 'src.components.common.EditDetailsModal.save',
    defaultMessage: 'Save',
  },
  saving: {
    id: 'src.components.common.EditDetailsModal.saving',
    defaultMessage: 'Saving...',
  },
});
