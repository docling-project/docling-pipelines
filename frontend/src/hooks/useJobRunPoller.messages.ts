import { defineMessages } from 'react-intl';

export const messages = defineMessages({
  runCompleted: {
    id: 'src.hooks.useJobRunPoller.runCompleted',
    defaultMessage: 'Execution of the flow {name} completed successfully.',
  },
  runCompletedWithIssues: {
    id: 'src.hooks.useJobRunPoller.runCompletedWithIssues',
    defaultMessage: 'Execution of the flow {name} completed with issues.',
  },
  runFailed: {
    id: 'src.hooks.useJobRunPoller.runFailed',
    defaultMessage: 'Execution of the flow {name} failed.',
  },
});
