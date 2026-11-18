/*
 * Licensed Materials - Property of IBM
 * © Copyright IBM Corp. 2024, 2026.
 */

import React from 'react';
import { ErrorFilled, WarningAlt, Close } from '@carbon/react/icons';
import { useIntl } from 'react-intl';
import { messages } from './TopNotificationBar.messages';
import styles from './TopNotificationBar.module.scss';

interface TopNotificationBarProps {
  errorCount: number;
  warningCount: number;
  onViewClick: () => void;
  onClose: () => void;
}

const TopNotificationBar: React.FC<TopNotificationBarProps> = ({
  errorCount,
  warningCount,
  onViewClick,
  onClose,
}) => {
  const intl = useIntl();
  const totalCount = errorCount + warningCount;

  if (totalCount === 0) {
    return null;
  }

  const hasOnlyWarnings = warningCount > 0 && errorCount === 0;

  const getMessage = (): string => {
    const parts: string[] = [];

    if (errorCount > 0) {
      parts.push(errorCount === 1
        ? intl.formatMessage(messages.errorSingular)
        : intl.formatMessage(messages.errorPlural, { count: errorCount }));
    }

    if (warningCount > 0) {
      parts.push(warningCount === 1
        ? intl.formatMessage(messages.warningSingular)
        : intl.formatMessage(messages.warningPlural, { count: warningCount }));
    }

    const allSingular = (errorCount === 0 || errorCount === 1) && (warningCount === 0 || warningCount === 1);
    const joined = parts.join(' and ');
    return allSingular
      ? intl.formatMessage(messages.messageSingularIs, { parts: joined })
      : intl.formatMessage(messages.messagePluralAre, { parts: joined });
  };

  const getTitle = (): string => (hasOnlyWarnings
    ? intl.formatMessage(messages.validationWarningTitle)
    : intl.formatMessage(messages.validationFailedTitle));

  const barClassName = hasOnlyWarnings
    ? `${styles.topNotificationBar} ${styles.warningBar}`
    : styles.topNotificationBar;

  return (
    <div className={barClassName}>
      <div className={styles.content}>
        {hasOnlyWarnings ? (
          <WarningAlt className={styles.warningIcon} />
        ) : (
          <ErrorFilled className={styles.errorIcon} />
        )}
        <span className={styles.title}>{getTitle()}</span>
        <span className={styles.message}>{getMessage()}</span>
      </div>
      <div className={styles.actions}>
        <button type="button" className={styles.viewLink} onClick={onViewClick}>
          {intl.formatMessage(messages.view)}
        </button>
        <button
          type="button"
          className={styles.closeButton}
          onClick={onClose}
          aria-label={intl.formatMessage(messages.closeNotification)}
        >
          <Close size={16} />
        </button>
      </div>
    </div>
  );
};

export default TopNotificationBar;
