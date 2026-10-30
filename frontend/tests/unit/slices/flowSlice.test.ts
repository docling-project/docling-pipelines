import { describe, it, expect } from 'vitest';
import reducer, {
  setFlows,
  setFlow,
  updateFlow,
  removeFlow,
  setCurrentFlow,
  clearFlow,
  setLoading,
  setError,
  clearError,
  setFlowRunProperties,
  updateFlowRunProperty,
  resetFlowRunProperties,
  fetchFlow,
  saveFlow,
} from '@/slices/flowSlice';
import type { FlowState, FlowRow } from '@/types';

const initialState: FlowState = {
  items: {},
  currentFlow: null,
  flowRunProperties: {
    enableIncrementalProcessing: false,
    retainRecordsForDeletedDocuments: false,
    validateFlow: true,
    enableNodeOutputPreview: false,
    intermediateDataStorage: 'container',
  },
  loading: false,
  error: null,
};

const flowRowFixture: FlowRow = {
  flow_id: 'flow-1',
  project_id: 'proj-1',
  name: 'Test Flow',
  description: 'A test flow',
  tags: [],
  run_count: 0,
  run_status: { errors: 0, warnings: 0, running: 0 },
  created_on: 'Jan 1, 2024',
  modified_on: 'Jan 2, 2024',
};

describe('flowSlice', () => {
  it('returns initial state', () => {
    expect(reducer(undefined, { type: '@@INIT' })).toEqual(initialState);
  });

  it('setFlows replaces items map', () => {
    const state = reducer(initialState, setFlows({ 'flow-1': flowRowFixture }));
    expect(state.items['flow-1']).toEqual(flowRowFixture);
  });

  it('setFlow inserts a single flow row', () => {
    const state = reducer(initialState, setFlow({ flowId: 'flow-1', flow: flowRowFixture }));
    expect(state.items['flow-1']).toEqual(flowRowFixture);
  });

  it('updateFlow merges partial updates into existing row', () => {
    const base = reducer(initialState, setFlow({ flowId: 'flow-1', flow: flowRowFixture }));
    const updated = reducer(base, updateFlow({ flowId: 'flow-1', updates: { name: 'Updated Name' } }));
    expect(updated.items['flow-1']?.name).toBe('Updated Name');
    expect(updated.items['flow-1']?.description).toBe('A test flow');
  });

  it('updateFlow is a no-op for unknown flowId', () => {
    const state = reducer(initialState, updateFlow({ flowId: 'unknown', updates: { name: 'x' } }));
    expect(state.items).toEqual({});
  });

  it('removeFlow deletes the flow by id', () => {
    const base = reducer(initialState, setFlow({ flowId: 'flow-1', flow: flowRowFixture }));
    const state = reducer(base, removeFlow('flow-1'));
    expect(state.items['flow-1']).toBeUndefined();
  });

  it('setCurrentFlow stores full flow object', () => {
    const flow = { flow_id: 'flow-1', name: 'Test', definition: {} } as never;
    const state = reducer(initialState, setCurrentFlow(flow));
    expect(state.currentFlow).toEqual(flow);
  });

  it('clearFlow sets currentFlow to null', () => {
    const flow = { flow_id: 'flow-1' } as never;
    const withFlow = reducer(initialState, setCurrentFlow(flow));
    const cleared = reducer(withFlow, clearFlow());
    expect(cleared.currentFlow).toBeNull();
  });

  it('setLoading sets loading flag', () => {
    const state = reducer(initialState, setLoading(true));
    expect(state.loading).toBe(true);
  });

  it('setError sets error and clears loading', () => {
    const withLoading = reducer(initialState, setLoading(true));
    const state = reducer(withLoading, setError('something went wrong'));
    expect(state.error).toBe('something went wrong');
    expect(state.loading).toBe(false);
  });

  it('setError with null clears the error', () => {
    const withErr = reducer(initialState, setError('oops'));
    const cleared = reducer(withErr, setError(null));
    expect(cleared.error).toBeNull();
  });

  it('clearError removes existing error', () => {
    const withErr = reducer(initialState, setError('oops'));
    const cleared = reducer(withErr, clearError());
    expect(cleared.error).toBeNull();
  });

  it('setFlowRunProperties replaces all run properties', () => {
    const props = {
      enableIncrementalProcessing: true,
      retainRecordsForDeletedDocuments: true,
      validateFlow: false,
      enableNodeOutputPreview: true,
      intermediateDataStorage: 'memory' as const,
    };
    const state = reducer(initialState, setFlowRunProperties(props));
    expect(state.flowRunProperties).toEqual(props);
  });

  it('updateFlowRunProperty updates a single key', () => {
    const state = reducer(initialState, updateFlowRunProperty({ key: 'validateFlow', value: false }));
    expect(state.flowRunProperties.validateFlow).toBe(false);
    expect(state.flowRunProperties.enableIncrementalProcessing).toBe(false);
  });

  it('resetFlowRunProperties restores defaults', () => {
    const changed = reducer(initialState, setFlowRunProperties({
      enableIncrementalProcessing: true,
      retainRecordsForDeletedDocuments: true,
      validateFlow: false,
      enableNodeOutputPreview: true,
      intermediateDataStorage: 'memory',
    }));
    const reset = reducer(changed, resetFlowRunProperties());
    expect(reset.flowRunProperties).toEqual(initialState.flowRunProperties);
  });

  // extraReducers — fetchFlow
  it('fetchFlow.pending clears error', () => {
    const withErr = reducer(initialState, setError('old error'));
    const state = reducer(withErr, { type: fetchFlow.pending.type });
    expect(state.error).toBeNull();
  });

  it('fetchFlow.fulfilled sets currentFlow and populates items', () => {
    const flow = { flow_id: 'flow-99', name: 'My Flow', definition: {} } as never;
    const state = reducer(initialState, { type: fetchFlow.fulfilled.type, payload: flow });
    expect(state.currentFlow).toEqual(flow);
    expect(state.items['flow-99']).toBeDefined();
    expect(state.error).toBeNull();
  });

  it('fetchFlow.rejected stores error message', () => {
    const state = reducer(initialState, {
      type: fetchFlow.rejected.type,
      payload: 'fetch failed',
    });
    expect(state.error).toBe('fetch failed');
  });

  it('fetchFlow.rejected falls back to Unknown error when payload is undefined', () => {
    const state = reducer(initialState, {
      type: fetchFlow.rejected.type,
      payload: undefined,
    });
    expect(state.error).toBe('Unknown error');
  });

  // extraReducers — saveFlow
  it('saveFlow.pending clears error', () => {
    const withErr = reducer(initialState, setError('old'));
    const state = reducer(withErr, { type: saveFlow.pending.type });
    expect(state.error).toBeNull();
  });

  it('saveFlow.fulfilled updates currentFlow', () => {
    const flow = { flow_id: 'flow-1', name: 'Saved', definition: {} } as never;
    const state = reducer(initialState, { type: saveFlow.fulfilled.type, payload: flow });
    expect(state.currentFlow).toEqual(flow);
    expect(state.error).toBeNull();
  });

  it('saveFlow.rejected stores error message', () => {
    const state = reducer(initialState, {
      type: saveFlow.rejected.type,
      payload: 'save failed',
    });
    expect(state.error).toBe('save failed');
  });

  it('saveFlow.rejected falls back to Unknown error when payload undefined', () => {
    const state = reducer(initialState, {
      type: saveFlow.rejected.type,
      payload: undefined,
    });
    expect(state.error).toBe('Unknown error');
  });
});
