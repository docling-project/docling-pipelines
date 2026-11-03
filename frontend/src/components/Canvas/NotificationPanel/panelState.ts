/*
 * Licensed Materials - Property of IBM
 * © Copyright IBM Corp. 2024, 2026.
 */

import type { NotificationItem } from './BottomNotificationPanel/BottomNotificationPanel';

// ── Module-level persistent store ────────────────────────────────────────────
// Survives component re-mounts (e.g. flyout open/close cycles that unmount Canvas subtree).
// Lives in its own file so NotificationPanel.tsx only exports components (React Fast Refresh).
export const panelState = {
  isOpen: false,
  showTopBar: false,
  topBarDismissed: false,
  notifications: [] as NotificationItem[],
};

/** Resets the persistent store to its initial values. */
export const resetPanelState = (): void => {
  panelState.isOpen = false;
  panelState.showTopBar = false;
  panelState.topBarDismissed = false;
  panelState.notifications = [];
};
