import { defineMessages } from 'react-intl';

export const messages = defineMessages({
  modalTitle: {
    id: 'src.components.Home.SampleProjectModal.modalTitle',
    defaultMessage: 'Setting up your sample project',
  },
  description: {
    id: 'src.components.Home.SampleProjectModal.description',
    defaultMessage: 'We are creating a sample project and pre-loading a ready-to-use ingestion pipeline.',
  },
  stepCreatingProject: {
    id: 'src.components.Home.SampleProjectModal.stepCreatingProject',
    defaultMessage: 'Creating project',
  },
  stepCreatingSampleFlow: {
    id: 'src.components.Home.SampleProjectModal.stepCreatingSampleFlow',
    defaultMessage: 'Creating sample flow',
  },
  stepCreatingFlowNamed: {
    id: 'src.components.Home.SampleProjectModal.stepCreatingFlowNamed',
    defaultMessage: 'Creating flow: {name}',
  },
  stepUsingExistingProject: {
    id: 'src.components.Home.SampleProjectModal.stepUsingExistingProject',
    defaultMessage: 'Using existing project',
  },
  errorTitle: {
    id: 'src.components.Home.SampleProjectModal.errorTitle',
    defaultMessage: 'Setup failed',
  },
  genericError: {
    id: 'src.components.Home.SampleProjectModal.genericError',
    defaultMessage: 'Something went wrong. Please try again.',
  },
  close: {
    id: 'src.components.Home.SampleProjectModal.close',
    defaultMessage: 'Close',
  },
});
