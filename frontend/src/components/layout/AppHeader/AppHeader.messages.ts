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
});
