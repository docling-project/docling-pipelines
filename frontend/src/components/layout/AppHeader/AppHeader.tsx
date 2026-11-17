import React, { useCallback, useEffect, useId, useRef, useState } from 'react';
import {
  Button,
  Header,
  HeaderName,
  HeaderNavigation,
  HeaderMenuItem,
  HeaderGlobalBar,
  HeaderGlobalAction,
  Popover,
  PopoverContent,
  Tag,
  Theme,
} from '@carbon/react';
import { Asleep, Light, Notification, UserAvatar } from '@carbon/icons-react';
import { useNavigate, useLocation } from 'react-router-dom';
import { useIntl } from 'react-intl';
import { go } from '@/utils';
import { useTheme, useAppDispatch } from '@/hooks';
import { useAuth } from '@/hooks/useAuth';
import { logoutUser } from '@/slices/authSlice';
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
 * - A profile menu as the rightmost global action, rendered only when auth is
 *   enabled and a user is signed in. The profile button opens a popover
 *   anchored under it (bottom-end) with the display name, email, role tags and
 *   a full-width "Sign out" button. The popover closes on sign-out, on outside
 *   click and on Escape; only Escape returns focus to the profile button, so
 *   outside clicks and tabbing away keep focus where the user moved it.
 */
export function AppHeader(): React.JSX.Element {
  const intl = useIntl();
  const { isDarkMode, toggleTheme } = useTheme();
  const navigate = useNavigate();
  const location = useLocation();
  const dispatch = useAppDispatch();
  const { user, authEnabled } = useAuth();

  const unreadCount = useAppSelector(selectNotificationUnreadCount);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [profileOpen, setProfileOpen] = useState(false);
  const profileButtonRef = useRef<HTMLButtonElement>(null);
  const profileTitleId = useId();

  const handleLogoClick = useCallback((): void => { go(navigate, ROUTES.HOME); }, [navigate]);
  const handleNavHome = useCallback((): void => { go(navigate, ROUTES.HOME); }, [navigate]);
  const handleNavProjects = useCallback((): void => { go(navigate, ROUTES.PROJECTS); }, [navigate]);

  const closeProfile = useCallback((): void => { setProfileOpen(false); }, []);

  const dismissProfile = useCallback((): void => {
    closeProfile();
    profileButtonRef.current?.focus();
  }, [closeProfile]);

  // Carbon closes the popover on Escape only while focus is inside its content,
  // so listen on the window to also cover focus that stays on the profile button.
  useEffect(() => {
    if (!profileOpen) { return undefined; }
    const handleKeyDown = (event: KeyboardEvent): void => {
      if (event.key === 'Escape') { dismissProfile(); }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => { window.removeEventListener('keydown', handleKeyDown); };
  }, [profileOpen, dismissProfile]);

  const handleSignOut = useCallback((): void => {
    setProfileOpen(false);
    void (async () => {
      await dispatch(logoutUser());
      void navigate(ROUTES.LOGIN);
    })();
  }, [dispatch, navigate]);

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

          {/* Profile menu — rightmost global action, only for a signed-in user */}
          {authEnabled && user && (
            <>
              <div className={styles.globalActionSeparator} />
              <Popover
                open={profileOpen}
                onRequestClose={closeProfile}
                align="bottom-end"
                caret={false}
              >
                <HeaderGlobalAction
                  ref={profileButtonRef}
                  aria-label={intl.formatMessage(messages.userMenuLabel)}
                  aria-expanded={profileOpen}
                  aria-haspopup="dialog"
                  onClick={() => { setProfileOpen((open) => !open); }}
                  isActive={profileOpen}
                  tooltipAlignment="end"
                >
                  <UserAvatar size={20} />
                </HeaderGlobalAction>
                {profileOpen && (
                  <PopoverContent>
                    <div className={styles.profilePanel} role="dialog" aria-labelledby={profileTitleId}>
                      <h2 id={profileTitleId} className={styles.profileName}>
                        {user.full_name || user.username}
                      </h2>
                      {user.email && <p className={styles.profileEmail}>{user.email}</p>}
                      {user.roles.length > 0 && (
                        <div
                          className={styles.profileRoles}
                          role="group"
                          aria-label={intl.formatMessage(messages.rolesLabel)}
                        >
                          {user.roles.map((role) => (
                            <Tag key={role} type="gray" size="sm">
                              {role.charAt(0).toUpperCase() + role.slice(1)}
                            </Tag>
                          ))}
                        </div>
                      )}
                      <hr className={styles.profileDivider} />
                      <Button
                        kind="ghost"
                        size="md"
                        className={styles.profileSignOut}
                        onClick={handleSignOut}
                      >
                        {intl.formatMessage(messages.signOut)}
                      </Button>
                    </div>
                  </PopoverContent>
                )}
              </Popover>
            </>
          )}
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
