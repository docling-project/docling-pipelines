import React, { useCallback, useState } from 'react';
import {
  Header,
  HeaderName,
  HeaderNavigation,
  HeaderMenuItem,
  HeaderGlobalBar,
  HeaderGlobalAction,
  Tag,
  Theme,
} from '@carbon/react';
import { Asleep, Light, Notification } from '@carbon/icons-react';
import { useNavigate, useLocation } from 'react-router-dom';
import { useIntl } from 'react-intl';
import { go } from '@/utils';
import { useTheme } from '@/hooks';
import { useAppSelector } from '@/hooks/useAppSelector';
import { selectNotificationUnreadCount } from '@/selectors';
import { ROUTES, APP_INFO } from '@/config';
import { NotificationHistory } from '@/components/common';
import { messages } from './AppHeader.messages';
import styles from './AppHeader.module.scss';

/**
 * Application top navigation bar.
 *
 * Renders the IBM product header with:
 * - A logo/product name that navigates to `/home` on click.
 * - Primary navigation menu items (Home, Projects).
 * - A notification bell that opens the {@link NotificationHistory} panel.
 *   Shows an unread badge when `state.notifications.unreadCount > 0`.
 * - A theme toggle button (light ↔ dark) in the global actions bar.
 */
export function AppHeader(): React.JSX.Element {
  const intl = useIntl();
  const { isDarkMode, toggleTheme } = useTheme();
  const navigate = useNavigate();
  const location = useLocation();

  const unreadCount = useAppSelector(selectNotificationUnreadCount);
  const [historyOpen, setHistoryOpen] = useState(false);

  const handleLogoClick = useCallback((): void => { go(navigate, ROUTES.HOME); }, [navigate]);
  const handleNavHome = useCallback((): void => { go(navigate, ROUTES.HOME); }, [navigate]);
  const handleNavProjects = useCallback((): void => { go(navigate, ROUTES.PROJECTS); }, [navigate]);
  return (
    <>
      {/* Always render the header in g100 so it stays dark in both light and dark modes,
          matching the IBM watsonx pattern of a persistent dark navigation bar. */}
      <Theme theme="g100">
      <Header aria-label={APP_INFO.NAME} className={styles.header}>
        <HeaderName
          prefix=""
          onClick={handleLogoClick}
          className={styles.headerName}
        >
          {APP_INFO.NAME}
        </HeaderName>
        <span className={styles.betaTag}>
          <Tag type="teal" size="sm">Beta</Tag>
        </span>
        <HeaderNavigation aria-label={intl.formatMessage(messages.mainNavLabel)}>
          <HeaderMenuItem
            onClick={handleNavHome}
            isActive={location.pathname === ROUTES.HOME}
          >
            {intl.formatMessage(messages.navHome)}
          </HeaderMenuItem>
          <HeaderMenuItem
            onClick={handleNavProjects}
            isActive={location.pathname === ROUTES.PROJECTS}
          >
            {intl.formatMessage(messages.navProjects)}
          </HeaderMenuItem>
        </HeaderNavigation>
        <HeaderGlobalBar className={styles.globalActions}>
          <div className={styles.globalActionSeparator} />

          {/* Notification bell — badge shows unread count */}
          <div className={styles.bellWrapper}>
            <HeaderGlobalAction
              aria-label={
                unreadCount > 0
                  ? intl.formatMessage(messages.notificationsUnread, { count: unreadCount })
                  : intl.formatMessage(messages.notifications)
              }
              onClick={() => { setHistoryOpen((o) => !o); }}
              isActive={historyOpen}
              className={styles.bellButton}
            >
              <Notification size={20} />
            </HeaderGlobalAction>
            {unreadCount > 0 && (
              <span className={styles.badge} aria-hidden="true">
                {unreadCount > 99 ? '99+' : unreadCount}
              </span>
            )}
          </div>

          <div className={styles.globalActionSeparator} />
          <HeaderGlobalAction
            aria-label={isDarkMode ? intl.formatMessage(messages.switchToLight) : intl.formatMessage(messages.switchToDark)}
            onClick={toggleTheme}
            className={styles.themeButton}
            tooltipAlignment="end"
          >
            {isDarkMode ? <Light size={20} /> : <Asleep size={20} />}
          </HeaderGlobalAction>
        </HeaderGlobalBar>
      </Header>
      </Theme>

      {/* History panel — rendered outside Header so it can overlap the page */}
      <NotificationHistory
        open={historyOpen}
        onClose={() => { setHistoryOpen(false); }}
      />
    </>
  );
}
