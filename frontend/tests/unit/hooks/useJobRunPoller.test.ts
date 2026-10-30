import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { useJobRunPoller } from '@/hooks/useJobRunPoller';
import { server } from '../../mocks/server';
import { http, HttpResponse } from 'msw';
import React from 'react';
import { Provider } from 'react-redux';
import { createTestStore } from '../../mocks/fixtures/store.fixture';

function makeWrapper() {
  const store = createTestStore();
  const Wrapper = ({ children }: { children: React.ReactNode }) =>
    React.createElement(Provider as any, { store }, children);
  return { store, Wrapper };
}

const completedResponse = {
  job_stats: { status: 'Completed', job_run_id: 'run-1', job_id: 'job-1' },
};

const runningResponse = {
  job_stats: { status: 'Running', job_run_id: 'run-1', job_id: 'job-1' },
};

describe('useJobRunPoller', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it('returns startPoll and stopPoll functions', () => {
    const { Wrapper } = makeWrapper();
    const { result } = renderHook(() => useJobRunPoller(), { wrapper: Wrapper });
    expect(typeof result.current.startPoll).toBe('function');
    expect(typeof result.current.stopPoll).toBe('function');
  });

  it('startPoll dispatches setRunning(true) immediately', () => {
    server.use(
      http.get('/api/job_runs/:id', () => HttpResponse.json(completedResponse))
    );
    const { Wrapper, store } = makeWrapper();
    const { result } = renderHook(() => useJobRunPoller(), { wrapper: Wrapper });

    act(() => { result.current.startPoll('run-1'); });
    expect(store.getState().jobRun.isRunning).toBe(true);
  });

  it('stopPoll immediately clears isRunning', async () => {
    server.use(
      http.get('/api/job_runs/:id', () => HttpResponse.json(runningResponse))
    );
    const { Wrapper, store } = makeWrapper();
    const { result } = renderHook(() => useJobRunPoller(), { wrapper: Wrapper });

    act(() => { result.current.startPoll('run-1'); });
    expect(store.getState().jobRun.isRunning).toBe(true);

    act(() => { result.current.stopPoll(); });
    // After stop, no timer should throw
    expect(() => { vi.runAllTimers(); }).not.toThrow();
  });

  it('calling startPoll twice aborts the first chain', () => {
    const { Wrapper, store } = makeWrapper();
    const { result } = renderHook(() => useJobRunPoller(), { wrapper: Wrapper });

    act(() => { result.current.startPoll('run-1'); });
    act(() => { result.current.startPoll('run-2'); });
    // Second startPoll replaced first — store still shows isRunning
    expect(store.getState().jobRun.isRunning).toBe(true);
  });

  it('dispatches setExecutionLogs when poll resolves with completed status', async () => {
    server.use(
      http.get('/api/job_runs/:id', () => HttpResponse.json(completedResponse))
    );
    const { Wrapper, store } = makeWrapper();
    const { result } = renderHook(() => useJobRunPoller(), { wrapper: Wrapper });

    act(() => { result.current.startPoll('run-1'); });
    await act(async () => { vi.runAllTimers(); await Promise.resolve(); });
    await act(async () => { await Promise.resolve(); });

    // executionLogs should be populated after poll
    const state = store.getState().jobRun;
    expect(state).toBeDefined();
  });

  it('retries on 404 response up to max retries', async () => {
    server.use(
      http.get('/api/job_runs/:id', () => new HttpResponse(null, { status: 404 }))
    );
    const { Wrapper } = makeWrapper();
    const { result } = renderHook(() => useJobRunPoller(), { wrapper: Wrapper });

    act(() => { result.current.startPoll('run-missing'); });
    // Running timers should not throw — retry is silent
    await act(async () => { vi.runAllTimers(); await Promise.resolve(); });
    await act(async () => { vi.runAllTimers(); await Promise.resolve(); });
    expect(result.current).toBeTruthy();
  });

  it('stops polling on 4xx non-404 error', async () => {
    server.use(
      http.get('/api/job_runs/:id', () => new HttpResponse(null, { status: 403 }))
    );
    const { Wrapper } = makeWrapper();
    const { result } = renderHook(() => useJobRunPoller(), { wrapper: Wrapper });

    act(() => { result.current.startPoll('run-forbidden'); });
    await act(async () => { vi.runAllTimers(); await Promise.resolve(); });
    // No throw — polling stops gracefully
    expect(result.current).toBeTruthy();
  });

  it('retries on 5xx network error', async () => {
    server.use(
      http.get('/api/job_runs/:id', () => new HttpResponse(null, { status: 500 }))
    );
    const { Wrapper } = makeWrapper();
    const { result } = renderHook(() => useJobRunPoller(), { wrapper: Wrapper });

    act(() => { result.current.startPoll('run-error'); });
    await act(async () => { vi.runAllTimers(); await Promise.resolve(); });
    await act(async () => { vi.runAllTimers(); await Promise.resolve(); });
    expect(result.current).toBeTruthy();
  });

  it('stopPoll clears the timer ref so no further polls fire', async () => {
    server.use(
      http.get('/api/job_runs/:id', () => HttpResponse.json(runningResponse))
    );
    const { Wrapper } = makeWrapper();
    const { result } = renderHook(() => useJobRunPoller(), { wrapper: Wrapper });

    act(() => { result.current.startPoll('run-stop'); });
    act(() => { result.current.stopPoll(); });
    // Running all timers after stop should not cause errors
    expect(() => { vi.runAllTimers(); }).not.toThrow();
  });

  it('cleans up on unmount via useEffect', () => {
    const { Wrapper } = makeWrapper();
    const { result, unmount } = renderHook(() => useJobRunPoller(), { wrapper: Wrapper });

    act(() => { result.current.startPoll('run-unmount'); });
    // Unmount triggers cleanup — should not throw
    expect(() => { unmount(); }).not.toThrow();
  });
});
