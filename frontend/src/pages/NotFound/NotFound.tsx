import React from 'react';
import { useIntl } from 'react-intl';
import { useNavigate } from 'react-router-dom';
import { Home } from '@carbon/icons-react';
import { NotFoundEmptyState } from '@carbon/ibm-products';
import { PageLayout } from '@/components';
import { ROUTES } from '@/config';
import { useTheme } from '@/hooks';
import { messages } from './NotFound.messages';
import styles from './NotFound.module.scss';

export function NotFound(): React.JSX.Element {
  const intl = useIntl();
  const navigate = useNavigate();
  const { isDarkMode } = useTheme();

  return (
    <PageLayout>
      <div className={styles.container}>
        <NotFoundEmptyState
          illustrationTheme={isDarkMode ? 'dark' : 'light'}
          title={intl.formatMessage(messages.title)}
          subtitle={intl.formatMessage(messages.subtitle)}
          action={{
            text: intl.formatMessage(messages.goHome),
            onClick: () => { void navigate(ROUTES.HOME); },
            renderIcon: Home,
            kind: 'tertiary',
          }}
        />
      </div>
    </PageLayout>
  );
}
