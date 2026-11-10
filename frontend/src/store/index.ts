/**
 * @fileoverview Redux store configuration for the Docling Pipelines application.
 * Configures the central Redux store with all state slices and exports type-safe types.
 */

import { configureStore } from '@reduxjs/toolkit';
import operatorsReducer from '@/slices/operatorsSlice';
import flowReducer from '@/slices/flowSlice';
import jobRunReducer from '@/slices/jobRunSlice';
import assetsReducer from '@/slices/assetsSlice';
import projectsReducer from '@/slices/projectsSlice';
import notificationsReducer from '@/slices/notificationsSlice';
import authReducer from '@/slices/authSlice';

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
  reducer: {
    operators: operatorsReducer,
    flow: flowReducer,
    jobRun: jobRunReducer,
    assets: assetsReducer,
    projects: projectsReducer,
    notifications: notificationsReducer,
    auth: authReducer,
  },
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
