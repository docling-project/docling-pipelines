import { combineReducers, configureStore, type Reducer } from '@reduxjs/toolkit';
import operatorsReducer from '@/slices/operatorsSlice';
import flowReducer from '@/slices/flowSlice';
import jobRunReducer from '@/slices/jobRunSlice';
import assetsReducer from '@/slices/assetsSlice';
import projectsReducer from '@/slices/projectsSlice';
import notificationsReducer from '@/slices/notificationsSlice';
import authReducer, { LOCAL_ADMIN_USER } from '@/slices/authSlice';
import type { AuthRole, AuthState } from '@/types';
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
  auth: authReducer,
});

/**
 * Auth state for tests that render as a specific role.
 * Produces an authenticated, auth-enabled session for `username` holding `role`.
 */
export function authStateFixture({
  role = 'admin',
  username = 'test-user',
  overrides,
}: {
  role?: AuthRole;
  username?: string;
  overrides?: Partial<AuthState>;
} = {}): AuthState {
  return {
    user: { username, email: `${username}@example.com`, full_name: username, roles: [role] },
    authEnabled: true,
    providers: [],
    credentialLogin: true,
    status: 'authenticated',
    error: null,
    errorStatus: null,
    retryAfter: null,
    ...overrides,
  };
}

/** Default auth state: authenticated with auth disabled (admin-equivalent), so existing tests are unaffected. */
const authDisabledState: AuthState = {
  user: LOCAL_ADMIN_USER,
  authEnabled: false,
  providers: [],
  credentialLogin: false,
  status: 'authenticated',
  error: null,
  errorStatus: null,
  retryAfter: null,
};

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
    auth: authDisabledState,
  };

  return { ...defaults, ...overrides };
}

export function createTestStore(preloadedState?: Partial<RootState>) {
  return configureStore({
    reducer: rootReducer as Reducer<RootState>,
    preloadedState: preloadedState as any,
  });
}
