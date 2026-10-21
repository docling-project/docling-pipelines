/**
 * @fileoverview Global toast container.
 *
 * Reads `state.notifications.active` from the Redux store and renders a
 * `@carbon/react` `ToastNotification` for each entry. Mounted once in
 * `App.tsx` — never rendered per-page.
 *
 * Auto-dismiss behaviour:
 * - If `notification.dismissAfter` is explicitly `0` → sticky (no timeout).
 * - If `notification.dismissAfter` is a positive number → use that value.
 * - Otherwise fall back to `preferences.dismissDelay` when `autoDismiss` is true.
 * - `error` notifications default to sticky via `useNotify`.
 */

import React from 'react';
import { ToastNotification } from '@carbon/react';
import { useIntl } from 'react-intl';
import { useAppSelector } from '@/hooks/useAppSelector';
import { useAppDispatch } from '@/hooks/useAppDispatch';
import { removeNotification } from '@/slices/notificationsSlice';
import { selectActiveNotifications, selectNotificationPreferences } from '@/selectors';
import { messages } from './ToastContainer.messages';
import styles from './ToastContainer.module.scss';

export function ToastContainer(): React.JSX.Element {
  const intl = useIntl();
  const dispatch = useAppDispatch();
  const active = useAppSelector(selectActiveNotifications);
  const preferences = useAppSelector(selectNotificationPreferences);

  return (
    <div className={styles.container} aria-live="polite" aria-label={intl.formatMessage(messages.ariaLabel)}>
      {active.map((notification) => {
        // Resolve the timeout:
        //   dismissAfter === 0          → sticky
        //   dismissAfter > 0            → use that value (ms)
        //   dismissAfter undefined      → use preference if autoDismiss is on
        let timeout: number;
        if (notification.dismissAfter === 0) {
          timeout = 0;
        } else if (notification.dismissAfter !== undefined) {
          timeout = notification.dismissAfter;
        } else {
          timeout = preferences.autoDismiss ? preferences.dismissDelay : 0;
        }

        return (
          <ToastNotification
            key={notification.id}
            kind={notification.kind}
            title={notification.title}
            subtitle={notification.subtitle}
            caption={notification.caption}
            timeout={timeout}
            onClose={() => { dispatch(removeNotification(notification.id)); }}
            aria-label={`${notification.kind} notification: ${notification.title}`}
          />
        );
      })}
    </div>
  );
}
