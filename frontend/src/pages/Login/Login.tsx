import React, { useState, useEffect, useRef, lazy, Suspense } from 'react';
import { useIntl } from 'react-intl';
import {
  Form,
  TextInput,
  PasswordInput,
  Button,
  InlineNotification,
  InlineLoading,
  Stack,
  Theme,
} from '@carbon/react';
import { ArrowRight, Flow, Login as LoginIcon } from '@carbon/icons-react';
import {
  watsonXAnimatedDark,
  watsonXAnimatedLight,
} from '@carbon-labs/react-animated-header';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { useAppDispatch, useAppSelector, useTheme } from '@/hooks';
import {
  selectAuthError,
  selectAuthProviders,
  selectAuthState,
  selectAuthStatus,
  selectCredentialLogin,
} from '@/selectors';
import { loginUser } from '@/slices/authSlice';
import { sanitizeReturnTo } from '@/utils/return-to';
import { LoginHeader } from './LoginHeader';
import { messages } from './Login.messages';
import styles from './Login.module.scss';

const AnimatedBackground = lazy(
  () => import('@carbon-labs/react-animated-header/es/components/AnimatedBackground/AnimatedBackground')
);

/**
 * Log-in page rendered outside the application shell.
 *
 * Slim {@link LoginHeader} on top, then a split-screen layout: a brand panel with the same
 * animated watsonx hero artwork as the Home page (dark animation in a `g100` zone, light
 * animation in a `g10` zone, following the app theme; collapsing to a compact tagline strip
 * below the `lg` breakpoint) beside the form panel. Supports credential login and OIDC providers depending on backend
 * auth configuration.
 */
export function Login(): React.JSX.Element {
  const intl = useIntl();
  const dispatch = useAppDispatch();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const { isDarkMode } = useTheme();

  const status = useAppSelector(selectAuthStatus);
  const error = useAppSelector(selectAuthError);
  const { errorStatus } = useAppSelector(selectAuthState);
  const credentialLogin = useAppSelector(selectCredentialLogin);
  const providers = useAppSelector(selectAuthProviders);

  const usernameInputRef = useRef<HTMLInputElement>(null);
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [usernameError, setUsernameError] = useState('');
  const [passwordError, setPasswordError] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);

  const rawReturnTo = searchParams.get('return_to');
  const returnTo = sanitizeReturnTo(rawReturnTo) ?? '/projects';

  useEffect(() => {
    if (status === 'authenticated') {
      void navigate(returnTo, { replace: true });
    }
  }, [status, navigate, returnTo]);

  const handleUsernameBlur = (): void => {
    if (!username.trim()) {
      setUsernameError(intl.formatMessage(messages.usernameRequired));
    }
  };

  const handlePasswordBlur = (): void => {
    if (!password.trim()) {
      setPasswordError(intl.formatMessage(messages.passwordRequired));
    }
  };

  const handleSubmit = (e: React.FormEvent): void => {
    e.preventDefault();

    let hasError = false;
    if (!username.trim()) {
      setUsernameError(intl.formatMessage(messages.usernameRequired));
      hasError = true;
    } else {
      setUsernameError('');
    }

    if (!password.trim()) {
      setPasswordError(intl.formatMessage(messages.passwordRequired));
      hasError = true;
    } else {
      setPasswordError('');
    }

    if (hasError) {
      return;
    }

    setIsSubmitting(true);
    void (async () => {
      try {
        const resultAction = await dispatch(loginUser({ username, password }));
        if (loginUser.rejected.match(resultAction)) {
          setPassword('');
          usernameInputRef.current?.focus();
        }
      } finally {
        setIsSubmitting(false);
      }
    })();
  };

  const renderNotification = (): React.JSX.Element | null => {
    if (!error) {
      return null;
    }

    let displayMessage = error;
    if (errorStatus === 429) {
      displayMessage = intl.formatMessage(messages.errorRetryLater);
    }

    return (
      <InlineNotification
        kind="error"
        title={intl.formatMessage(messages.title)}
        subtitle={displayMessage}
        hideCloseButton
        lowContrast
        role="alert"
        className={styles.notification}
      />
    );
  };

  const getProviderUrl = (authorizeUrl: string): string => {
    const isSafeRelative = authorizeUrl.startsWith('/') && !authorizeUrl.startsWith('//');
    const isSafeHttps = authorizeUrl.startsWith('https://');
    if (!isSafeRelative && !isSafeHttps) {
      return '#';
    }
    const separator = authorizeUrl.includes('?') ? '&' : '?';
    return `${authorizeUrl}${separator}return_to=${encodeURIComponent(returnTo)}`;
  };

  const hasCredentialLogin = credentialLogin;
  const hasProviders = providers && providers.length > 0;

  return (
    <>
      <LoginHeader />
      <main className={styles.page}>
        <Theme theme={isDarkMode ? 'g100' : 'g10'} className={styles.brandPanel}>
          <div className={styles.illustrationWrapper} aria-hidden="true" data-testid="login-illustration-wrapper">
            <Suspense fallback={null}>
              <AnimatedBackground
                headerAnimation={(isDarkMode ? watsonXAnimatedDark : watsonXAnimatedLight) as object}
                isOpen={false}
              />
            </Suspense>
          </div>
          <div className={styles.brandContent}>
            <p className={styles.tagline}>{intl.formatMessage(messages.tagline)}</p>
          </div>
        </Theme>

        <section className={styles.formPanel}>
          <div className={styles.formContent}>
            <Stack gap={6}>
              <div>
                <Flow size={32} className={styles.appMark} aria-hidden="true" />
                <h1 className={styles.title}>{intl.formatMessage(messages.title)}</h1>
                <p className={styles.helper}>{intl.formatMessage(messages.formHelper)}</p>
              </div>

              {!hasCredentialLogin && !hasProviders && (
                <InlineNotification
                  kind="error"
                  title={intl.formatMessage(messages.title)}
                  subtitle={intl.formatMessage(messages.errorNoLoginMethod)}
                  hideCloseButton
                  lowContrast
                  role="alert"
                  className={styles.notification}
                />
              )}

              {renderNotification()}

              {hasCredentialLogin && (
                <Form onSubmit={handleSubmit}>
                  <Stack gap={6}>
                    <TextInput
                      ref={usernameInputRef}
                      id="username"
                      labelText={intl.formatMessage(messages.usernameLabel)}
                      placeholder={intl.formatMessage(messages.usernamePlaceholder)}
                      autoComplete="username"
                      autoFocus
                      value={username}
                      onChange={(e) => {
                        setUsername(e.target.value);
                        if (usernameError) {
                          setUsernameError('');
                        }
                      }}
                      onBlur={handleUsernameBlur}
                      invalid={Boolean(usernameError)}
                      invalidText={usernameError}
                      disabled={isSubmitting}
                    />
                    <PasswordInput
                      id="password"
                      labelText={intl.formatMessage(messages.passwordLabel)}
                      placeholder={intl.formatMessage(messages.passwordPlaceholder)}
                      autoComplete="current-password"
                      value={password}
                      onChange={(e) => {
                        setPassword(e.target.value);
                        if (passwordError) {
                          setPasswordError('');
                        }
                      }}
                      onBlur={handlePasswordBlur}
                      invalid={Boolean(passwordError)}
                      invalidText={passwordError}
                      disabled={isSubmitting}
                    />
                    <Button
                      type="submit"
                      size="lg"
                      renderIcon={isSubmitting ? undefined : ArrowRight}
                      className={styles.fullWidthBtn}
                      disabled={isSubmitting}
                    >
                      {isSubmitting ? (
                        <InlineLoading description={intl.formatMessage(messages.logInLoading)} />
                      ) : (
                        intl.formatMessage(messages.logInButton)
                      )}
                    </Button>
                  </Stack>
                </Form>
              )}

              {hasCredentialLogin && hasProviders && (
                <div className={styles.divider}>
                  {intl.formatMessage(messages.dividerOr)}
                </div>
              )}

              {hasProviders && (
                <Stack gap={4}>
                  {providers.map((provider) => (
                    <Button
                      key={provider.name}
                      kind="tertiary"
                      size="lg"
                      renderIcon={LoginIcon}
                      className={styles.fullWidthBtn}
                      onClick={() => {
                        const targetUrl = getProviderUrl(provider.authorize_url);
                        if (targetUrl !== '#') {
                          window.location.assign(targetUrl);
                        }
                      }}
                    >
                      {intl.formatMessage(messages.providerButton, { provider: provider.display_name })}
                    </Button>
                  ))}
                </Stack>
              )}
            </Stack>

            <p className={styles.footer}>{intl.formatMessage(messages.footer)}</p>
          </div>
        </section>
      </main>
    </>
  );
}
