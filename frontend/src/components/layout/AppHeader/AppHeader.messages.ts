import { defineMessages } from 'react-intl';

export const messages = defineMessages({
  navHome: {
    id: 'src.components.layout.AppHeader.navHome',
    defaultMessage: 'Home',
  },
  navProjects: {
    id: 'src.components.layout.AppHeader.navProjects',
    defaultMessage: 'Projects',
  },
  mainNavLabel: {
    id: 'src.components.layout.AppHeader.mainNavLabel',
    defaultMessage: 'Main navigation',
  },
  notificationsUnread: {
    id: 'src.components.layout.AppHeader.notificationsUnread',
    defaultMessage: 'Notifications ({count} unread)',
  },
  notifications: {
    id: 'src.components.layout.AppHeader.notifications',
    defaultMessage: 'Notifications',
  },
  switchToLight: {
    id: 'src.components.layout.AppHeader.switchToLight',
    defaultMessage: 'Switch to light mode',
  },
  switchToDark: {
    id: 'src.components.layout.AppHeader.switchToDark',
    defaultMessage: 'Switch to dark mode',
  },
  userMenuLabel: {
    id: 'src.components.layout.AppHeader.userMenuLabel',
    defaultMessage: 'User menu',
  },
  signOut: {
    id: 'src.components.layout.AppHeader.signOut',
    defaultMessage: 'Sign out',
  },
  signOutFailedTitle: {
    id: 'src.components.layout.AppHeader.signOutFailedTitle',
    defaultMessage: 'Sign-out incomplete',
  },
  signOutFailedSubtitle: {
    id: 'src.components.layout.AppHeader.signOutFailedSubtitle',
    defaultMessage: 'Could not reach the server to end your session. Your server session may still be active.',
  },
  rolesLabel: {
    id: 'src.components.layout.AppHeader.rolesLabel',
    defaultMessage: 'Roles',
  },
});
