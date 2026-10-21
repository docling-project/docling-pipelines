/**
 * @fileoverview Notification history slide-in panel.
 *
 * Triggered by the bell icon in `AppHeader`. Displays all notifications
 * logged this session in reverse-chronological order. The user can clear
 * the history or dismiss individual entries from the panel.
 *
 * Opening the panel dispatches `markHistoryRead` to reset the bell badge.
 */

import React, { useEffect } from 'react';
import { Button } from '@carbon/react';
import {
  Close,
  TrashCan,
  CheckmarkFilled,
  ErrorFilled,
  WarningAltFilled,
  InformationFilled,
} from '@carbon/icons-react';
import { useIntl } from 'react-intl';
import { useAppSelector } from '@/hooks/useAppSelector';
import { useAppDispatch } from '@/hooks/useAppDispatch';
import { clearHistory, markHistoryRead } from '@/slices/notificationsSlice';
import { selectNotificationHistory } from '@/selectors';
import type { Notification } from '@/types/notifications';
import { messages } from './NotificationHistory.messages';
import styles from './NotificationHistory.module.scss';

interface NotificationHistoryProps {
  readonly open: boolean;
  readonly onClose: () => void;
}

// ─── Kind → icon + CSS class ──────────────────────────────────────────────────

type KindMeta = {
  Icon: React.ComponentType<{ size?: number; className?: string }>;
  iconClass: string;
};

const KIND_META: Record<Notification['kind'], KindMeta> = {
  success: { Icon: CheckmarkFilled,   iconClass: styles.iconSuccess },
  error:   { Icon: ErrorFilled,       iconClass: styles.iconError   },
  warning: { Icon: WarningAltFilled,  iconClass: styles.iconWarning },
  info:    { Icon: InformationFilled, iconClass: styles.iconInfo    },
};

// ─── Helpers ──────────────────────────────────────────────────────────────────

function formatTimestamp(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    month:  'short',
    day:    'numeric',
    year:   'numeric',
    hour:   '2-digit',
    minute: '2-digit',
  });
}

// ─── Component ────────────────────────────────────────────────────────────────

export function NotificationHistory({
  open,
  onClose,
}: NotificationHistoryProps): React.JSX.Element | null {
  const intl = useIntl();
  const dispatch = useAppDispatch();
  const history = useAppSelector(selectNotificationHistory);

  useEffect(() => {
    if (open) {
      dispatch(markHistoryRead());
    }
  }, [open, dispatch]);

  if (!open) { return null; }

  return (
    <>
      <div className={styles.overlay} onClick={onClose} aria-hidden="true" />

      <aside className={styles.panel} aria-label={intl.formatMessage(messages.panelAriaLabel)} role="complementary">
        {/* Header */}
        <div className={styles.header}>
          <h2 className={styles.title}>{intl.formatMessage(messages.panelTitle)}</h2>
          <div className={styles.headerActions}>
            {history.length > 0 && (
              <Button
                kind="ghost"
                size="sm"
                renderIcon={TrashCan}
                iconDescription={intl.formatMessage(messages.clearAll)}
                hasIconOnly
                tooltipPosition="bottom"
                onClick={() => { dispatch(clearHistory()); }}
                aria-label={intl.formatMessage(messages.clearAll)}
              />
            )}
            <Button
              kind="ghost"
              size="sm"
              renderIcon={Close}
              iconDescription={intl.formatMessage(messages.closePanel)}
              hasIconOnly
              tooltipPosition="bottom"
              onClick={onClose}
              aria-label={intl.formatMessage(messages.closePanel)}
            />
          </div>
        </div>

        {/* Body */}
        <div className={styles.body}>
          {history.length === 0 ? (
            <p className={styles.empty}>{intl.formatMessage(messages.empty)}</p>
          ) : (
            <ul className={styles.list} aria-label={intl.formatMessage(messages.historyListLabel)}>
              {history.map((notification) => {
                const { Icon, iconClass } = KIND_META[notification.kind];
                return (
                  <li key={notification.id} className={styles.item}>
                    <Icon size={16} className={`${styles.icon} ${iconClass}`} />
                    <div className={styles.itemContent}>
                      <p className={styles.itemTitle}>{notification.title}</p>
                      {notification.subtitle && (
                        <p className={styles.itemSubtitle}>{notification.subtitle}</p>
                      )}
                      <span className={styles.timestamp}>
                        {formatTimestamp(notification.timestamp)}
                      </span>
                    </div>
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      </aside>
    </>
  );
}
