/**
 * API Services Module
 *
 * Central export point for all API-related functionality
 */

// Validation
export { validateFlow } from './actions/validation-actions';
export type { FlowValidationResponse, ValidationAlertItem, ValidationActionType } from './actions/validation-actions';

// Operators
export { getOperatorMetadata, enrichFlowFeatures, getProviderModels } from './actions/operator-actions';

// Document Classes
export { getDocumentClasses } from './actions/document-class-actions';

// Flows
export {
  createFlow,
  getFlow,
  getFlows,
  getFlowsByProjectId,
  updateFlow,
  patchFlow,
  deleteFlow,
  bulkDeleteFlows,
} from './actions/flow-actions';

// Job Runs
export {
  createJobRun,
  getJobRuns,
  getJobRun,
  cancelJobRun,
  deleteJobRun,
  downloadJobRunReport,
  getJobRunFlowDefinition,
} from './actions/job-run-actions';

// Projects
export {
  createProject,
  getProjects,
  getProject,
  replaceProject,
  patchProject,
  deleteProject,
} from './actions/project-actions';

// Flow mapper (full namespace — same usage pattern as projectMapper)
export * as flowMapper from './mappers/flow-mapper';
// Deprecated alias kept for any callers not yet migrated
export { flowResponseToRow } from './mappers/flow-mapper';

// Client
export { apiClient } from './client';
