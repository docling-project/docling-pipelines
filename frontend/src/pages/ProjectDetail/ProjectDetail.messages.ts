import { defineMessages } from 'react-intl';

export const messages = defineMessages({
  projectNotFound: {
    id: 'src.pages.ProjectDetail.projectNotFound',
    defaultMessage: 'Project not found.',
  },
  projectLoadError: {
    id: 'src.pages.ProjectDetail.projectLoadError',
    defaultMessage: 'Failed to load project. Please try again.',
  },
  flowsLoadError: {
    id: 'src.pages.ProjectDetail.flowsLoadError',
    defaultMessage: 'Failed to load flows. Please try again.',
  },
  unexpectedError: {
    id: 'src.pages.ProjectDetail.unexpectedError',
    defaultMessage: 'An unexpected error occurred.',
  },
  createFlowSuccess: {
    id: 'src.pages.ProjectDetail.createFlowSuccess',
    defaultMessage: '{name} created successfully.',
  },
  createFlowError: {
    id: 'src.pages.ProjectDetail.createFlowError',
    defaultMessage: 'Failed to create flow',
  },
  defaultFlowName: {
    id: 'src.pages.ProjectDetail.defaultFlowName',
    defaultMessage: 'Flow',
  },
  deleteFlowSuccess: {
    id: 'src.pages.ProjectDetail.deleteFlowSuccess',
    defaultMessage: '{name} deleted successfully.',
  },
  deleteFlowError: {
    id: 'src.pages.ProjectDetail.deleteFlowError',
    defaultMessage: '{name} failed to delete.',
  },
  updateFlowSuccess: {
    id: 'src.pages.ProjectDetail.updateFlowSuccess',
    defaultMessage: '{name} updated successfully.',
  },
  updateFlowError: {
    id: 'src.pages.ProjectDetail.updateFlowError',
    defaultMessage: 'Failed to update flow',
  },
  created: {
    id: 'src.pages.ProjectDetail.created',
    defaultMessage: 'Created: <b>{date}</b>',
  },
  lastUpdated: {
    id: 'src.pages.ProjectDetail.lastUpdated',
    defaultMessage: 'Last updated: <b>{date}</b>',
  },
  flows: {
    id: 'src.pages.ProjectDetail.flows',
    defaultMessage: 'Flows: <b>{count}</b>',
  },
  expandDetails: {
    id: 'src.pages.ProjectDetail.expandDetails',
    defaultMessage: 'Expand project details',
  },
  collapseDetails: {
    id: 'src.pages.ProjectDetail.collapseDetails',
    defaultMessage: 'Collapse project details',
  },
  emptyTitle: {
    id: 'src.pages.ProjectDetail.emptyTitle',
    defaultMessage: 'No flows created',
  },
  createFlow: {
    id: 'src.pages.ProjectDetail.createFlow',
    defaultMessage: 'Create flow',
  },
});
