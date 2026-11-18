import React from 'react';
import { useIntl } from 'react-intl';
import { useNavigate, useLocation } from 'react-router-dom';
import { Home } from '@carbon/icons-react';
import { ErrorEmptyState, NotFoundEmptyState } from '@carbon/ibm-products';
import { PageLayout } from '@/components';
import { ROUTES } from '@/config';
import { useTheme } from '@/hooks';
import { messages } from './Error.messages';
import styles from './Error.module.scss';

interface ErrorState {
  message?: string;
  statusCode?: number;
}

export function Error(): React.JSX.Element {
  const intl = useIntl();
  const navigate = useNavigate();
  const location = useLocation();
  const { isDarkMode } = useTheme();
  const state = location.state as ErrorState | undefined;

  const errorMessage = state?.message ?? intl.formatMessage(messages.defaultErrorMessage);
  const statusCode = state?.statusCode ?? 500;

  const goHomeAction = {
    text: intl.formatMessage(messages.goHome),
    onClick: () => { void navigate(ROUTES.HOME); },
    renderIcon: Home,
    kind: 'tertiary' as const,
  };

  return (
    <PageLayout>
      <div className={styles.container}>
        {statusCode === 404 ? (
          <NotFoundEmptyState
            illustrationTheme={isDarkMode ? 'dark' : 'light'}
            title={intl.formatMessage(messages.notFoundTitle)}
            subtitle={errorMessage}
            action={goHomeAction}
          />
        ) : (
          <ErrorEmptyState
            illustrationTheme={isDarkMode ? 'dark' : 'light'}
            title={intl.formatMessage(messages.errorTitle)}
            subtitle={errorMessage}
            action={goHomeAction}
          />
        )}
      </div>
    </PageLayout>
  );
}
