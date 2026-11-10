import { defineMessages } from 'react-intl';

export const messages = defineMessages({
  appName: {
    id: 'src.pages.Login.appName',
    defaultMessage: 'Docling Pipelines',
  },
  title: {
    id: 'src.pages.Login.title',
    defaultMessage: 'Sign in',
  },
  usernameLabel: {
    id: 'src.pages.Login.usernameLabel',
    defaultMessage: 'Username',
  },
  usernamePlaceholder: {
    id: 'src.pages.Login.usernamePlaceholder',
    defaultMessage: 'Enter username',
  },
  passwordLabel: {
    id: 'src.pages.Login.passwordLabel',
    defaultMessage: 'Password',
  },
  passwordPlaceholder: {
    id: 'src.pages.Login.passwordPlaceholder',
    defaultMessage: 'Enter password',
  },
  signInButton: {
    id: 'src.pages.Login.signInButton',
    defaultMessage: 'Sign in',
  },
  signInLoading: {
    id: 'src.pages.Login.signInLoading',
    defaultMessage: 'Signing in...',
  },
  dividerOr: {
    id: 'src.pages.Login.dividerOr',
    defaultMessage: 'or',
  },
  errorRequired: {
    id: 'src.pages.Login.errorRequired',
    defaultMessage: 'This field is required',
  },
  errorRetryLater: {
    id: 'src.pages.Login.errorRetryLater',
    defaultMessage: 'Too many failed attempts. Please retry later.',
  },
  errorNoSignInMethod: {
    id: 'src.pages.Login.errorNoSignInMethod',
    defaultMessage: 'No sign-in method is currently configured.',
  },
  providerButton: {
    id: 'src.pages.Login.providerButton',
    defaultMessage: 'Sign in with {provider}',
  },
});
