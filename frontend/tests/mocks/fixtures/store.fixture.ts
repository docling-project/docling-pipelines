import { combineReducers, configureStore, type Reducer } from '@reduxjs/toolkit';
import operatorsReducer from '@/slices/operatorsSlice';
import flowReducer from '@/slices/flowSlice';
import jobRunReducer from '@/slices/jobRunSlice';
import assetsReducer from '@/slices/assetsSlice';
import projectsReducer from '@/slices/projectsSlice';
import notificationsReducer from '@/slices/notificationsSlice';
import type { RootState } from '@/store';
import { flowFixture, flowRowFixture } from './flow.fixture';
import { projectDomainFixture } from './project.fixture';

export const rootReducer = combineReducers({
  operators: operatorsReducer,
  flow: flowReducer,
  jobRun: jobRunReducer,
  assets: assetsReducer,
  projects: projectsReducer,
  notifications: notificationsReducer,
});

/**
 * Creates a pre-configured store with optional preloaded state.
 * Use this in component tests via renderWithProviders.
 */
export function buildPreloadedState(
  overrides?: Partial<RootState>
): Partial<RootState> {
  const defaults: Partial<RootState> = {
    flow: {
      items: { 'flow-1': flowRowFixture },
      currentFlow: flowFixture,
      flowRunProperties: {
        enableIncrementalProcessing: false,
        retainRecordsForDeletedDocuments: false,
        validateFlow: true,
        enableNodeOutputPreview: false,
        intermediateDataStorage: 'container',
      },
      loading: false,
      error: null,
    },
    projects: {
      items: { 'project-1': projectDomainFixture },
      selectedProjectId: null,
      loading: false,
      error: null,
    },
    assets: {
      flows: {},
      jobRuns: {},
      selectedFlowId: null,
      selectedJobRunId: null,
    },
    jobRun: {
      items: {},
      byJobId: {},
      selectedRunId: null,
      logs: {},
      statistics: {},
      loading: false,
      error: null,
      isRunning: false,
      currentJobRunId: null,
      currentJobId: null,
      executionLogs: null,
    },
    operators: {
      metadata: {},
      featureOptions: {},
      nodeFeatures: {},
      loading: false,
      featuresLoading: false,
      error: null,
    },
    notifications: {
      active: [],
      history: [],
      preferences: { autoDismiss: true, dismissDelay: 5000 },
      unreadCount: 0,
    },
  };

  return { ...defaults, ...overrides };
}

export function createTestStore(preloadedState?: Partial<RootState>) {
  return configureStore({
    reducer: rootReducer as Reducer<RootState>,
    preloadedState: preloadedState as any,
  });
}
