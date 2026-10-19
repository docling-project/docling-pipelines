import { defineMessages } from 'react-intl';

export const messages = defineMessages({
  title: {
    id: 'src.components.cards.RunsCard.title',
    defaultMessage: 'Runs',
  },
  loading: {
    id: 'src.components.cards.RunsCard.loading',
    defaultMessage: 'Loading runs...',
  },
  refreshDescription: {
    id: 'src.components.cards.RunsCard.refreshDescription',
    defaultMessage: 'Refresh runs',
  },
  emptyTitle: {
    id: 'src.components.cards.RunsCard.emptyTitle',
    defaultMessage: 'No runs',
  },
  emptySubtitle: {
    id: 'src.components.cards.RunsCard.emptySubtitle',
    defaultMessage: 'Runs will be listed here.',
  },
  loadError: {
    id: 'src.components.cards.RunsCard.loadError',
    defaultMessage: 'Failed to load runs.',
  },
  runCompleted: {
    id: 'src.components.cards.RunsCard.runCompleted',
    defaultMessage: 'Execution of "{label}" flow at {time} completed.',
  },
  runFailed: {
    id: 'src.components.cards.RunsCard.runFailed',
    defaultMessage: 'Execution of "{label}" flow at {time} failed.',
  },
});
