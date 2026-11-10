import { defineMessages } from 'react-intl';

export const messages = defineMessages({
  title: {
    id: 'src.components.cards.ProjectsCard.title',
    defaultMessage: 'Projects',
  },
  loading: {
    id: 'src.components.cards.ProjectsCard.loading',
    defaultMessage: 'Loading projects...',
  },
  createIconDescription: {
    id: 'src.components.cards.ProjectsCard.createIconDescription',
    defaultMessage: 'Create project',
  },
  emptyTitle: {
    id: 'src.components.cards.ProjectsCard.emptyTitle',
    defaultMessage: 'No recent projects',
  },
  emptySubtitle: {
    id: 'src.components.cards.ProjectsCard.emptySubtitle',
    defaultMessage: 'After you create projects, you\'ll see them here.',
  },
  emptyActionText: {
    id: 'src.components.cards.ProjectsCard.emptyActionText',
    defaultMessage: 'Create project',
  },
  viewAll: {
    id: 'src.components.cards.ProjectsCard.viewAll',
    defaultMessage: 'View all',
  },
  loadError: {
    id: 'src.components.cards.ProjectsCard.loadError',
    defaultMessage: 'Failed to load projects.',
  },
  createError: {
    id: 'src.components.cards.ProjectsCard.createError',
    defaultMessage: 'Failed to create project.',
  },
  createSuccess: {
    id: 'src.components.cards.ProjectsCard.createSuccess',
    defaultMessage: '{name} created successfully.',
  },
});
