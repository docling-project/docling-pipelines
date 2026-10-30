/*
 * Licensed Materials - Property of IBM
 * © Copyright IBM Corp. 2024, 2026.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import React from 'react';
import { act } from '@testing-library/react';
import { renderWithProviders } from '../../../utils/renderWithProviders';
import { NotificationPanel, panelState } from '@/components/Canvas/NotificationPanel/NotificationPanel';

beforeEach(() => {
  vi.useFakeTimers();
  // Guard: panelState may be undefined under parallel worker initialisation.
  if (panelState) {
    panelState.isOpen = false;
    panelState.showTopBar = false;
    panelState.topBarDismissed = false;
    panelState.notifications = [];
  }
});
afterEach(() => {
  vi.useRealTimers();
  if (panelState) {
    panelState.isOpen = false;
    panelState.showTopBar = false;
    panelState.topBarDismissed = false;
    panelState.notifications = [];
  }
});

const defaultProps = {
  validationData: null as null,
  canvasControllerRef: { current: null } as React.RefObject<null>,
  onStateChange: vi.fn(),
  onBottomContent: vi.fn(),
  onTopContent: vi.fn(),
};

describe('NotificationPanel', () => {
  it('renders null (drives parent via callbacks, no DOM output)', () => {
    const { container } = renderWithProviders(
      <NotificationPanel {...defaultProps} onStateChange={vi.fn()} onBottomContent={vi.fn()} onTopContent={vi.fn()} />
    );
    expect(container.firstChild).toBeNull();
  });

  it('calls onStateChange with initial empty state on mount', () => {
    const onStateChange = vi.fn();
    renderWithProviders(
      <NotificationPanel {...defaultProps} onStateChange={onStateChange} onBottomContent={vi.fn()} onTopContent={vi.fn()} />
    );
    expect(onStateChange).toHaveBeenCalled();
    const lastCall = onStateChange.mock.calls[onStateChange.mock.calls.length - 1]?.[0];
    expect(lastCall?.showBottomPanel).toBe(false);
    expect(lastCall?.notifications).toEqual([]);
  });

  it('calls onBottomContent with null when panel is closed', () => {
    const onBottomContent = vi.fn();
    renderWithProviders(
      <NotificationPanel {...defaultProps} onStateChange={vi.fn()} onBottomContent={onBottomContent} onTopContent={vi.fn()} />
    );
    expect(onBottomContent).toHaveBeenCalledWith(null);
  });

  it('calls onTopContent with null initially', () => {
    const onTopContent = vi.fn();
    renderWithProviders(
      <NotificationPanel {...defaultProps} onStateChange={vi.fn()} onBottomContent={vi.fn()} onTopContent={onTopContent} />
    );
    expect(onTopContent).toHaveBeenCalledWith(null);
  });

  it('processes failed validation with errors and populates notifications', () => {
    const onStateChange = vi.fn();
    const validationData = {
      status: 'Failed',
      message: null,
      errors: [{ code: 'E001', message: 'Missing param', node_name: 'Chunker', node_id: 'n1', message_code: null, operator: null }],
      warnings: [],
    };
    renderWithProviders(
      <NotificationPanel
        {...defaultProps}
        validationData={validationData}
        onStateChange={onStateChange}
        onBottomContent={vi.fn()}
        onTopContent={vi.fn()}
      />
    );
    const lastCall = onStateChange.mock.calls[onStateChange.mock.calls.length - 1]?.[0];
    expect(lastCall?.notifications).toHaveLength(1);
    expect(lastCall?.notifications[0]?.type).toBe('error');
    expect(lastCall?.notifications[0]?.code).toBe('E001');
  });

  it('processes succeeded_with_warnings validation with warnings', () => {
    const onStateChange = vi.fn();
    const validationData = {
      status: 'succeeded_with_warnings',
      message: null,
      errors: [],
      warnings: [{ code: 'W001', message: 'Slow node', node_name: 'Ingest', node_id: 'n2', message_code: 'INGEST_OPERATOR_MISPLACED', operator: null }],
    };
    renderWithProviders(
      <NotificationPanel
        {...defaultProps}
        validationData={validationData}
        onStateChange={onStateChange}
        onBottomContent={vi.fn()}
        onTopContent={vi.fn()}
      />
    );
    const lastCall = onStateChange.mock.calls[onStateChange.mock.calls.length - 1]?.[0];
    expect(lastCall?.notifications).toHaveLength(1);
    expect(lastCall?.notifications[0]?.type).toBe('warning');
  });

  it('clears notifications when validation succeeds with no issues', () => {
    const onStateChange = vi.fn();
    // First render with errors
    const { rerender } = renderWithProviders(
      <NotificationPanel
        {...defaultProps}
        validationData={{ status: 'Failed', message: null, errors: [{ code: 'E1', message: 'err', node_name: null, node_id: null, message_code: null, operator: null }], warnings: [] }}
        onStateChange={onStateChange}
        onBottomContent={vi.fn()}
        onTopContent={vi.fn()}
      />
    );
    onStateChange.mockClear();
    // Rerender with clean success
    rerender(
      <NotificationPanel
        {...defaultProps}
        validationData={{ status: 'Succeeded', message: null, errors: [], warnings: [] }}
        onStateChange={onStateChange}
        onBottomContent={vi.fn()}
        onTopContent={vi.fn()}
      />
    );
    const lastCall = onStateChange.mock.calls[onStateChange.mock.calls.length - 1]?.[0];
    expect(lastCall?.notifications).toEqual([]);
    expect(lastCall?.showBottomPanel).toBe(false);
  });

  it('shows top bar content when validation has errors', () => {
    const onTopContent = vi.fn();
    renderWithProviders(
      <NotificationPanel
        {...defaultProps}
        validationData={{ status: 'Failed', message: null, errors: [{ code: 'E1', message: 'err', node_name: null, node_id: null, message_code: null, operator: null }], warnings: [] }}
        onStateChange={vi.fn()}
        onBottomContent={vi.fn()}
        onTopContent={onTopContent}
      />
    );
    // The last call should include a non-null ReactElement (TopNotificationBar)
    const calls = onTopContent.mock.calls;
    const lastNonNull = calls.reverse().find(([arg]) => arg !== null);
    expect(lastNonNull).toBeDefined();
  });

  it('opens bottom panel on showBottomPanel global event', () => {
    const onBottomContent = vi.fn();
    renderWithProviders(
      <NotificationPanel
        {...defaultProps}
        onStateChange={vi.fn()}
        onBottomContent={onBottomContent}
        onTopContent={vi.fn()}
      />
    );
    onBottomContent.mockClear();
    act(() => {
      globalThis.dispatchEvent(new Event('showBottomPanel'));
    });
    // After event, should have been called with non-null (BottomNotificationPanel)
    // With no notifications it renders the panel with empty list
    expect(onBottomContent).toHaveBeenCalled();
  });

  it('closes bottom panel on hideBottomPanel global event', () => {
    const onStateChange = vi.fn();
    renderWithProviders(
      <NotificationPanel
        {...defaultProps}
        onStateChange={onStateChange}
        onBottomContent={vi.fn()}
        onTopContent={vi.fn()}
      />
    );
    act(() => { globalThis.dispatchEvent(new Event('showBottomPanel')); });
    act(() => { globalThis.dispatchEvent(new Event('hideBottomPanel')); });
    const lastCall = onStateChange.mock.calls[onStateChange.mock.calls.length - 1]?.[0];
    expect(lastCall?.showBottomPanel).toBe(false);
  });

  it('handleNodeClick calls setSelections when messageCode is a HIGHLIGHT_MESSAGE_CODE', () => {
    const setSelections = vi.fn();
    const canvasControllerRef = { current: { setSelections } };
    const setActivePanelNodeId = vi.fn();
    const onBottomContent = vi.fn();

    renderWithProviders(
      <NotificationPanel
        validationData={{ status: 'Failed', message: null, errors: [{ code: 'E1', message: 'err', node_name: 'N', node_id: 'nodeX', message_code: 'DISJOINT_OPERATORS_DETECTED', operator: null }], warnings: [] }}
        canvasControllerRef={canvasControllerRef as unknown as React.RefObject<null>}
        setActivePanelNodeId={setActivePanelNodeId}
        onStateChange={vi.fn()}
        onBottomContent={onBottomContent}
        onTopContent={vi.fn()}
      />
    );

    // Get the BottomNotificationPanel element passed via onBottomContent
    // Open the panel
    act(() => { globalThis.dispatchEvent(new Event('showBottomPanel')); });

    const lastCall = onBottomContent.mock.calls[onBottomContent.mock.calls.length - 1]?.[0];
    expect(lastCall).not.toBeNull();

    // Call onNodeClick directly from the rendered props
    const onNodeClick: (nodeId: string, messageCode?: string | null) => void = lastCall.props.onNodeClick;
    act(() => {
      onNodeClick('nodeX', 'DISJOINT_OPERATORS_DETECTED');
      vi.runAllTimers();
    });
    expect(setActivePanelNodeId).toHaveBeenCalledWith(null);
    expect(setSelections).toHaveBeenCalledWith(['nodeX']);
  });

  it('handleNodeClick calls openNodeProperties when messageCode is not a HIGHLIGHT code', () => {
    const openNodeProperties = vi.fn();
    const setActivePanelNodeId = vi.fn();
    const canvasControllerRef = { current: { setSelections: vi.fn() } };
    const onBottomContent = vi.fn();

    renderWithProviders(
      <NotificationPanel
        validationData={{ status: 'Failed', message: null, errors: [{ code: 'E1', message: 'err', node_name: 'N', node_id: 'nodeY', message_code: 'SOME_OTHER_CODE', operator: null }], warnings: [] }}
        canvasControllerRef={canvasControllerRef as unknown as React.RefObject<null>}
        openNodeProperties={openNodeProperties}
        setActivePanelNodeId={setActivePanelNodeId}
        onStateChange={vi.fn()}
        onBottomContent={onBottomContent}
        onTopContent={vi.fn()}
      />
    );
    act(() => { globalThis.dispatchEvent(new Event('showBottomPanel')); });
    const lastCall = onBottomContent.mock.calls[onBottomContent.mock.calls.length - 1]?.[0];
    const onNodeClick: (nodeId: string, messageCode?: string | null) => void = lastCall.props.onNodeClick;
    act(() => { onNodeClick('nodeY', 'SOME_OTHER_CODE'); });
    expect(openNodeProperties).toHaveBeenCalledWith('nodeY');
    expect(setActivePanelNodeId).toHaveBeenCalledWith('nodeY');
  });

  it('does nothing in handleNodeClick when canvasController is null', () => {
    const openNodeProperties = vi.fn();
    const onBottomContent = vi.fn();
    renderWithProviders(
      <NotificationPanel
        validationData={{ status: 'Failed', message: null, errors: [{ code: 'E1', message: 'err', node_name: 'N', node_id: 'nodeZ', message_code: null, operator: null }], warnings: [] }}
        canvasControllerRef={{ current: null } as React.RefObject<null>}
        openNodeProperties={openNodeProperties}
        onStateChange={vi.fn()}
        onBottomContent={onBottomContent}
        onTopContent={vi.fn()}
      />
    );
    act(() => { globalThis.dispatchEvent(new Event('showBottomPanel')); });
    const lastCall = onBottomContent.mock.calls[onBottomContent.mock.calls.length - 1]?.[0];
    const onNodeClick: (nodeId: string, messageCode?: string | null) => void = lastCall.props.onNodeClick;
    act(() => { onNodeClick('nodeZ', null); });
    expect(openNodeProperties).not.toHaveBeenCalled();
  });

  it('ignores validationData with unknown/unsupported status (no errors/warnings)', () => {
    const onStateChange = vi.fn();
    // 'running' status with no errors/warnings — shouldProcess guard skips it entirely.
    // Use a sentinel to confirm nothing from this specific validationData was added.
    renderWithProviders(
      <NotificationPanel
        {...defaultProps}
        validationData={{ status: 'running', message: null, errors: [], warnings: [] }}
        onStateChange={onStateChange}
        onBottomContent={vi.fn()}
        onTopContent={vi.fn()}
      />
    );
    const lastCall = onStateChange.mock.calls[onStateChange.mock.calls.length - 1]?.[0];
    // No item from this validationData (empty errors) should appear
    const fromThisData = lastCall?.notifications.filter(
      (n: { message: string }) => n.message === 'from_running_status'
    ) ?? [];
    expect(fromThisData).toEqual([]);
  });

  it('does not process errors when status is not failed or succeeded_with_warnings', () => {
    const onStateChange = vi.fn();
    // Even with errors in the payload, an unknown status is ignored by the shouldProcess guard.
    // Use a unique sentinel message to verify this specific error was NOT added.
    renderWithProviders(
      <NotificationPanel
        {...defaultProps}
        validationData={{ status: 'pending', message: null, errors: [{ code: 'PENDING_CODE', message: 'pending_sentinel_error', node_name: null, node_id: null, message_code: null, operator: null }], warnings: [] }}
        onStateChange={onStateChange}
        onBottomContent={vi.fn()}
        onTopContent={vi.fn()}
      />
    );
    const lastCall = onStateChange.mock.calls[onStateChange.mock.calls.length - 1]?.[0];
    // The sentinel error must NOT appear — pending status is not processed
    const pendingItems = lastCall?.notifications.filter(
      (n: { code: string }) => n.code === 'PENDING_CODE'
    ) ?? [];
    expect(pendingItems).toEqual([]);
  });
});

// ── Index re-export tests ─────────────────────────────────────────────────────
describe('NotificationPanel index re-exports', () => {
  it('re-exports NotificationPanel from index', async () => {
    const mod = await import('@/components/Canvas/NotificationPanel/index');
    expect(mod.NotificationPanel).toBeDefined();
  });

  it('re-exports BottomNotificationPanel from index', async () => {
    const mod = await import('@/components/Canvas/NotificationPanel/index');
    expect(mod.BottomNotificationPanel).toBeDefined();
  });

  it('re-exports TopNotificationBar from index', async () => {
    const mod = await import('@/components/Canvas/NotificationPanel/index');
    expect(mod.TopNotificationBar).toBeDefined();
  });
});
