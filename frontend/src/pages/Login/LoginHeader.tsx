import React from 'react';
import { useIntl } from 'react-intl';
import {
  Header,
  HeaderName,
  HeaderGlobalBar,
  HeaderGlobalAction,
  Tag,
  Theme,
} from '@carbon/react';
import { Asleep, Light } from '@carbon/icons-react';
import { useTheme } from '@/hooks';
import { APP_INFO } from '@/config';
import { messages } from './Login.messages';
import styles from './LoginHeader.module.scss';

/**
 * Top bar for the login page.
 *
 * Keeps the exact styling and structure of {@link AppHeader} (g100 theme, product name,
 * Beta tag, separator, and theme toggle in the global actions bar), but omits authenticated
 * items (navigation, notification bell, user profile menu).
 */
export function LoginHeader(): React.JSX.Element {
  const intl = useIntl();
  const { isDarkMode, toggleTheme } = useTheme();

  return (
    <Theme theme="g100">
      <Header aria-label={APP_INFO.NAME} className={styles.header}>
        <HeaderName prefix="" className={styles.headerName}>
          {APP_INFO.NAME}
        </HeaderName>
        <span className={styles.betaTag}>
          <Tag type="teal" size="sm">Beta</Tag>
        </span>
        <HeaderGlobalBar className={styles.globalActions}>
          <div className={styles.globalActionSeparator} />
          <HeaderGlobalAction
            aria-label={
              isDarkMode
                ? intl.formatMessage(messages.switchToLight)
                : intl.formatMessage(messages.switchToDark)
            }
            onClick={toggleTheme}
            className={styles.themeButton}
            tooltipAlignment="end"
          >
            {isDarkMode ? <Light size={20} /> : <Asleep size={20} />}
          </HeaderGlobalAction>
        </HeaderGlobalBar>
      </Header>
    </Theme>
  );
}
