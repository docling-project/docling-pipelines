/**
 * @fileoverview Redux store configuration for the Docling Pipelines application.
 * Configures the central Redux store with all state slices and exports type-safe types.
 */

import { combineReducers, configureStore, type UnknownAction } from '@reduxjs/toolkit';
import operatorsReducer from '@/slices/operatorsSlice';
import flowReducer from '@/slices/flowSlice';
import jobRunReducer from '@/slices/jobRunSlice';
import assetsReducer from '@/slices/assetsSlice';
import projectsReducer from '@/slices/projectsSlice';
import notificationsReducer from '@/slices/notificationsSlice';
import authReducer, { logoutUser } from '@/slices/authSlice';

const combinedReducer = combineReducers({
  operators: operatorsReducer,
  flow: flowReducer,
  jobRun: jobRunReducer,
  assets: assetsReducer,
  projects: projectsReducer,
  notifications: notificationsReducer,
  auth: authReducer,
});

type CombinedState = ReturnType<typeof combinedReducer>;

/**
 * Root reducer that resets cached domain slices on user logout while preserving
 * static operator metadata and allowing the auth slice to transition normally.
 */
export function rootReducer(
  state: CombinedState | undefined,
  action: UnknownAction
): CombinedState {
  if (state !== undefined && (logoutUser.fulfilled.match(action) || logoutUser.rejected.match(action))) {
    return combinedReducer(
      {
        ...state,
        flow: undefined,
        jobRun: undefined,
        assets: undefined,
        projects: undefined,
        notifications: undefined,
      },
      action
    );
  }
  return combinedReducer(state, action);
}

/**
 * The Redux store instance for the application.
 * Combines all state slices into a single store with the following structure:
 * - operators: Operator metadata and feature options
 * - flow: Current flow with nested definition
 * - jobRun: Job run executions, logs, and statistics
 * - assets: Flows and job runs for navigation (legacy; will be split further)
 * - projects: Full project lifecycle — list, detail, loading, error
 * - auth: Current user, auth config and session status (no token is stored)
 */
export const store = configureStore({
  reducer: rootReducer,
});

/**
 * Type representing the complete Redux state tree.
 * Use this type with useAppSelector for type-safe state access.
 * @example
 * const operators = useAppSelector((state: RootState) => state.operators);
 */
export type RootState = ReturnType<typeof store.getState>;

/**
 * Type representing the Redux dispatch function.
 * Use this type with useAppDispatch for type-safe action dispatching.
 * @example
 * const dispatch = useAppDispatch();
 * dispatch(setCurrentFlow(flowData));
 */
export type AppDispatch = typeof store.dispatch;
