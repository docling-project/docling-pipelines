import { defineMessages } from 'react-intl';

export const messages = defineMessages({
  modalTitle: {
    id: 'src.components.ProjectDetail.CreateFlowTearsheet.modalTitle',
    defaultMessage: 'Create flow',
  },
  errorTitle: {
    id: 'src.components.ProjectDetail.CreateFlowTearsheet.errorTitle',
    defaultMessage: 'Failed to create flow',
  },
  nameLabel: {
    id: 'src.components.ProjectDetail.CreateFlowTearsheet.nameLabel',
    defaultMessage: 'Name',
  },
  namePlaceholder: {
    id: 'src.components.ProjectDetail.CreateFlowTearsheet.namePlaceholder',
    defaultMessage: 'Enter name',
  },
  nameDuplicate: {
    id: 'src.components.ProjectDetail.CreateFlowTearsheet.nameDuplicate',
    defaultMessage: 'A flow with this name already exists. Please choose a unique name.',
  },
  nameRequired: {
    id: 'src.components.ProjectDetail.CreateFlowTearsheet.nameRequired',
    defaultMessage: 'Name is required',
  },
  descriptionLabel: {
    id: 'src.components.ProjectDetail.CreateFlowTearsheet.descriptionLabel',
    defaultMessage: 'Description (optional)',
  },
  descriptionPlaceholder: {
    id: 'src.components.ProjectDetail.CreateFlowTearsheet.descriptionPlaceholder',
    defaultMessage: 'Enter description',
  },
  tagsLabel: {
    id: 'src.components.ProjectDetail.CreateFlowTearsheet.tagsLabel',
    defaultMessage: 'Add tags (optional)',
  },
  tagsHelperText: {
    id: 'src.components.ProjectDetail.CreateFlowTearsheet.tagsHelperText',
    defaultMessage: 'Add tags to make flow easier to find. To add tags, separate them with commas and press Enter.',
  },
  cancel: {
    id: 'src.components.ProjectDetail.CreateFlowTearsheet.cancel',
    defaultMessage: 'Cancel',
  },
  create: {
    id: 'src.components.ProjectDetail.CreateFlowTearsheet.create',
    defaultMessage: 'Create',
  },
  creating: {
    id: 'src.components.ProjectDetail.CreateFlowTearsheet.creating',
    defaultMessage: 'Creating...',
  },
});
