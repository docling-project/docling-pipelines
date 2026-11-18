/*
 * Licensed Materials - Property of IBM
 * © Copyright IBM Corp. 2024, 2026.
 */

/* eslint-disable @typescript-eslint/no-explicit-any */
import React, { useEffect, useRef, useState } from 'react';
import BottomNotificationPanel from './BottomNotificationPanel/BottomNotificationPanel';
import type { NotificationItem } from './BottomNotificationPanel/BottomNotificationPanel';
import TopNotificationBar from './TopNotificationBar/TopNotificationBar';
import { VALIDATION_STATUS, HIGHLIGHT_MESSAGE_CODES } from '@/constants/notificationPanel';
import type { FlowValidationResponse, ValidationActionType } from '@/services/api';

// ── Module-level persistent store ────────────────────────────────────────────
// Survives component re-mounts (e.g. flyout open/close cycles that unmount Canvas subtree).
const panelState = {
  isOpen: false,
  showTopBar: false,
  topBarDismissed: false,
  notifications: [] as NotificationItem[],
};

// ── Types ─────────────────────────────────────────────────────────────────────

export interface NotificationPanelState {
  /** Whether the bottom panel drawer is currently open. */
  showBottomPanel: boolean;
  /** Processed array of error/warning items. */
  notifications: NotificationItem[];
}

interface NotificationPanelProps {
  /** The latest validation response from the API (or null/undefined). */
  validationData: FlowValidationResponse | null | undefined;
  /** Elyra canvas controller ref — used for node selection. */
  canvasControllerRef: React.RefObject<any>;
  /** Callback to open a node's properties panel. */
  openNodeProperties?: (nodeId: string) => void;
  /** State setter to track which node's panel is open. */
  setActivePanelNodeId?: (nodeId: string | null) => void;
  /** Called whenever bottom panel open state or notifications change. */
  onStateChange: (state: NotificationPanelState) => void;
  /** Slot setter for the bottom panel content (passes JSX or null to parent). */
  onBottomContent: (content: React.ReactElement | null) => void;
  /** Slot setter for the top notification bar content (passes JSX or null to parent). */
  onTopContent: (content: React.ReactElement | null) => void;
}

// ── Component ─────────────────────────────────────────────────────────────────

/**
 * NotificationPanel
 *
 * Manages validation notification state and drives two UI slots in the canvas:
 * - A resizable bottom drawer (`onBottomContent`) showing errors/warnings in a table.
 * - A top alert banner (`onTopContent`) summarising error/warning counts.
 *
 * State changes (open/notifications) are reported back via `onStateChange` so
 * the parent (Canvas) can update its toolbar without re-owning this logic.
 */
export function NotificationPanel({
  validationData,
  canvasControllerRef,
  openNodeProperties,
  setActivePanelNodeId,
  onStateChange,
  onBottomContent,
  onTopContent,
}: NotificationPanelProps): null {
  // Lazy initialisers read the module-level store so state survives re-mounts.
  const [isOpen, setIsOpenState] = useState<boolean>(() => panelState.isOpen);
  const [showTopBar, setShowTopBarState] = useState<boolean>(() => panelState.showTopBar);
  const [topBarDismissed, setTopBarDismissedState] = useState<boolean>(() => panelState.topBarDismissed);
  const [notifications, setNotificationsState] = useState<NotificationItem[]>(
    () => panelState.notifications
  );

  // Synchronise local state + module store in one call
  const setIsOpen = (v: boolean): void => { panelState.isOpen = v; setIsOpenState(v); };
  const setShowTopBar = (v: boolean): void => { panelState.showTopBar = v; setShowTopBarState(v); };
  const setTopBarDismissed = (v: boolean): void => { panelState.topBarDismissed = v; setTopBarDismissedState(v); };
  const setNotifications = (v: NotificationItem[]): void => { panelState.notifications = v; setNotificationsState(v); };

  // Track the last processed validation data reference to detect new runs
  const lastValidationDataRef = useRef<FlowValidationResponse | null | undefined>(null);
  const lastValidationIdRef = useRef<string>('');

  // ── Process incoming validation data ─────────────────────────────────────
  useEffect(() => {
    if (!validationData) { return; }

    const status = (validationData.status ?? '').toLowerCase();
    const hasErrors = (validationData.errors?.length ?? 0) > 0;
    const hasWarnings = (validationData.warnings?.length ?? 0) > 0;

    // Successful run with no issues — clear everything
    if (status === VALIDATION_STATUS.SUCCEEDED && !hasErrors && !hasWarnings) {
      if (lastValidationIdRef.current !== '' || panelState.notifications.length > 0) {
        setNotifications([]);
        lastValidationIdRef.current = '';
        setShowTopBar(false);
        setTopBarDismissed(false);
        setIsOpen(false);
        lastValidationDataRef.current = validationData;
      }
      return;
    }

    const shouldProcess =
      status === VALIDATION_STATUS.FAILED ||
      status === VALIDATION_STATUS.SUCCEEDED_WITH_WARNINGS;

    if (!shouldProcess || (!hasErrors && !hasWarnings)) { return; }

    // Build notification items
    const timestamp = new Date().toLocaleString();
    const items: NotificationItem[] = [];

    validationData.errors?.forEach((item, index) => {
      items.push({
        id: `error-${item.code ?? 'unknown'}-${index}`,
        type: 'error',
        code: item.code,
        message: item.message,
        node_name: item.node_name,
        node_id: item.node_id,
        message_code: item.message_code,
        action_type: item.action_type,
        timestamp,
      });
    });

    validationData.warnings?.forEach((item, index) => {
      items.push({
        id: `warning-${item.code ?? 'unknown'}-${index}`,
        type: 'warning',
        code: item.code,
        message: item.message,
        node_name: item.node_name,
        node_id: item.node_id,
        message_code: item.message_code,
        action_type: item.action_type,
        timestamp,
      });
    });

    // Stable hash to detect content changes including message and action_type
    const errorHash = validationData.errors?.map((e) => `${e.code}-${e.node_id}-${e.message}-${e.action_type}`).join('|') ?? '';
    const warningHash = validationData.warnings?.map((w) => `${w.code}-${w.node_id}-${w.message}-${w.action_type}`).join('|') ?? '';
    const validationId = `${status}-${errorHash}-${warningHash}`;

    const isContentChanged = validationId !== lastValidationIdRef.current;
    const isNewRun = validationData !== lastValidationDataRef.current;

    if (isContentChanged) {
      setNotifications(items);
      lastValidationIdRef.current = validationId;
    }

    // Always show the top bar on a new validation run (even if content is the same)
    if (isNewRun) {
      setShowTopBar(true);
      setTopBarDismissed(false);
      lastValidationDataRef.current = validationData;
    }
  }, [validationData]);

  // ── Terminal toggle events ────────────────────────────────────────────────
  useEffect(() => {
    const handleShow = (): void => { setIsOpen(true); };
    const handleHide = (): void => { setIsOpen(false); };

    globalThis.addEventListener('showBottomPanel', handleShow);
    globalThis.addEventListener('hideBottomPanel', handleHide);

    return () => {
      globalThis.removeEventListener('showBottomPanel', handleShow);
      globalThis.removeEventListener('hideBottomPanel', handleHide);
      // Reset module-level store on unmount
      panelState.isOpen = false;
      panelState.showTopBar = false;
      panelState.topBarDismissed = false;
      panelState.notifications = [];
    };
  }, []);

  // ── Notify parent of state changes ───────────────────────────────────────
  useEffect(() => {
    onStateChange({ showBottomPanel: isOpen, notifications });
  }, [isOpen, notifications, onStateChange]);

  // ── Node click routing ────────────────────────────────────────────────────
  const handleNodeClick = (
    nodeId: string,
    messageCode?: string | null,
    actionType?: ValidationActionType | null
  ): void => {
    const canvasController = canvasControllerRef.current;
    if (!canvasController) { return; }

    // If action_type is explicitly provided by the backend:
    if (actionType === 'none') {
      return;
    }

    const shouldHighlight =
      actionType === 'highlight' ||
      (!actionType && Boolean(messageCode && HIGHLIGHT_MESSAGE_CODES.has(messageCode)));

    if (shouldHighlight) {
      // Close any open properties panel, then select/highlight the node
      if (setActivePanelNodeId) { setActivePanelNodeId(null); }
      // eslint-disable-next-line @typescript-eslint/no-unsafe-call, @typescript-eslint/no-unsafe-member-access
      setTimeout(() => { canvasController.setSelections([nodeId]); }, 0);
    } else if (openNodeProperties) {
      openNodeProperties(nodeId);
      if (setActivePanelNodeId) { setActivePanelNodeId(nodeId); }
    }
  };

  // ── Derived counts ────────────────────────────────────────────────────────
  const errorCount = notifications.filter((n) => n.type === 'error').length;
  const warningCount = notifications.filter((n) => n.type === 'warning').length;

  // ── Drive bottom panel slot ───────────────────────────────────────────────
  useEffect(() => {
    onBottomContent(
      isOpen ? (
        <BottomNotificationPanel
          notifications={notifications}
          onClose={() => { setIsOpen(false); }}
          onNodeClick={handleNodeClick}
        />
      ) : null
    );
  // handleNodeClick is intentionally omitted from deps — it is stable per render
  // and recreating it would cause unnecessary slot updates.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isOpen, notifications, onBottomContent]);

  // ── Drive top bar slot ────────────────────────────────────────────────────
  useEffect(() => {
    onTopContent(
      showTopBar && !topBarDismissed ? (
        <TopNotificationBar
          errorCount={errorCount}
          warningCount={warningCount}
          onViewClick={() => { setIsOpen(true); }}
          onClose={() => {
            setShowTopBar(false);
            setTopBarDismissed(true);
          }}
        />
      ) : null
    );
  }, [showTopBar, topBarDismissed, errorCount, warningCount, onTopContent]);

  // This component drives its output through callbacks — it renders no DOM of its own.
  return null;
}
