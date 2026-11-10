import React, { useState, useEffect } from 'react';
import { useIntl } from 'react-intl';
import { Form, TextInput, PasswordInput, Button, InlineNotification } from '@carbon/react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { useAppDispatch, useAppSelector } from '@/hooks';
import { loginUser } from '@/slices/authSlice';
import { sanitizeReturnTo } from '@/utils/return-to';
import { messages } from './Login.messages';
import styles from './Login.module.scss';

export function Login(): React.JSX.Element {
  const intl = useIntl();
  const dispatch = useAppDispatch();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();

  const { status, error, errorStatus, credentialLogin, providers } = useAppSelector((state) => state.auth);

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

  const handleSubmit = (e: React.FormEvent): void => {
    e.preventDefault();

    let hasError = false;
    if (!username.trim()) {
      setUsernameError(intl.formatMessage(messages.errorRequired));
      hasError = true;
    } else {
      setUsernameError('');
    }

    if (!password.trim()) {
      setPasswordError(intl.formatMessage(messages.errorRequired));
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
        await dispatch(loginUser({ username, password }));
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
        role="alert"
        className={styles.notification}
      />
    );
  };

  const getProviderUrl = (authorizeUrl: string): string => {
    const separator = authorizeUrl.includes('?') ? '&' : '?';
    return `${authorizeUrl}${separator}return_to=${encodeURIComponent(returnTo)}`;
  };

  const hasCredentialLogin = credentialLogin;
  const hasProviders = providers && providers.length > 0;

  return (
    <div className={styles.loginContainer}>
      <div className={styles.loginCard}>
        <div className={styles.header}>
          <div className={styles.appName}>{intl.formatMessage(messages.appName)}</div>
          <h1 className={styles.title}>{intl.formatMessage(messages.title)}</h1>
        </div>

        {!hasCredentialLogin && !hasProviders && (
          <InlineNotification
            kind="error"
            title={intl.formatMessage(messages.title)}
            subtitle={intl.formatMessage(messages.errorNoSignInMethod)}
            hideCloseButton
            role="alert"
            className={styles.notification}
          />
        )}

        {renderNotification()}

        {hasCredentialLogin && (
          <Form onSubmit={handleSubmit} className={styles.form}>
            <TextInput
              id="username"
              labelText={intl.formatMessage(messages.usernameLabel)}
              placeholder={intl.formatMessage(messages.usernamePlaceholder)}
              value={username}
              onChange={(e) => {
                setUsername(e.target.value);
                if (usernameError) {
                  setUsernameError('');
                }
              }}
              invalid={Boolean(usernameError)}
              invalidText={usernameError}
              disabled={isSubmitting}
            />
            <PasswordInput
              id="password"
              labelText={intl.formatMessage(messages.passwordLabel)}
              placeholder={intl.formatMessage(messages.hiddenFieldPlaceholder)}
              value={password}
              onChange={(e) => {
                setPassword(e.target.value);
                if (passwordError) {
                  setPasswordError('');
                }
              }}
              invalid={Boolean(passwordError)}
              invalidText={passwordError}
              disabled={isSubmitting}
            />
            <Button
              type="submit"
              className={styles.submitBtn}
              disabled={isSubmitting}
            >
              {isSubmitting ? intl.formatMessage(messages.signInLoading) : intl.formatMessage(messages.signInButton)}
            </Button>
          </Form>
        )}

        {hasCredentialLogin && hasProviders && (
          <div className={styles.divider}>
            {intl.formatMessage(messages.dividerOr)}
          </div>
        )}

        {hasProviders && (
          <div className={styles.providerSection}>
            {providers.map((provider) => (
              <Button
                key={provider.name}
                kind="secondary"
                className={styles.providerBtn}
                onClick={() => {
                  window.location.assign(getProviderUrl(provider.authorize_url));
                }}
              >
                {intl.formatMessage(messages.providerButton, { provider: provider.display_name })}
              </Button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
