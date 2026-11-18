import { defineMessages } from 'react-intl';

export const messages = defineMessages({
  metricsTitle: {
    id: 'src.components.FlowDetail.FlowMetrics.metricsTitle',
    defaultMessage: 'Run metrics ({total})',
  },
  labelRun: {
    id: 'src.components.FlowDetail.FlowMetrics.labelRun',
    defaultMessage: 'Run',
  },
  labelInProgress: {
    id: 'src.components.FlowDetail.FlowMetrics.labelInProgress',
    defaultMessage: 'In progress',
  },
  labelRunWithIssues: {
    id: 'src.components.FlowDetail.FlowMetrics.labelRunWithIssues',
    defaultMessage: 'Run with issues',
  },
  labelFailed: {
    id: 'src.components.FlowDetail.FlowMetrics.labelFailed',
    defaultMessage: 'Failed',
  },
  labelCancelled: {
    id: 'src.components.FlowDetail.FlowMetrics.labelCancelled',
    defaultMessage: 'Cancelled',
  },
});
