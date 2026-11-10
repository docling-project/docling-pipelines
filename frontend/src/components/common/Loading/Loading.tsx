import React from 'react';
import { Loading as CarbonLoading, InlineLoading } from '@carbon/react';
import { useIntl } from 'react-intl';
import { messages } from './Loading.messages';
import styles from './Loading.module.scss';

/**
 * Props for {@link Loading}.
 */
interface LoadingProps {
  /** Accessible description text shown alongside the spinner. Defaults to `'Loading...'`. */
  description?: string;
  /**
   * When `true`, renders Carbon's `InlineLoading` (compact, suitable for inline contexts
   * such as button labels or table cells).
   * When `false` (default), renders the full-screen `CarbonLoading` spinner.
   */
  inline?: boolean;
  /**
   * Status indicator for the inline variant.
   * Has no effect when `inline` is `false`.
   */
  status?: 'active' | 'inactive' | 'finished' | 'error';
  /**
   * When `true` (default), wraps the spinner in a flex container that centres it
   * within its parent. Set to `false` to let the spinner sit in normal document flow.
   * Has no effect when `inline` is `true`.
   */
  centered?: boolean;
}

/**
 * Thin wrapper around Carbon's `Loading` and `InlineLoading` components that
 * provides consistent loading states across the application.
 *
 * - Pass `inline` for compact in-context indicators (e.g. inside a button or table cell).
 * - Pass `centered` (default `true`) to vertically and horizontally centre the full spinner.
 */
export function Loading({
  description,
  inline = false,
  status = 'active',
  centered = true,
}: LoadingProps): React.JSX.Element {
  const intl = useIntl();
  const resolvedDescription = description ?? intl.formatMessage(messages.defaultDescription);
  if (inline) {
    return (
      <InlineLoading
        description={resolvedDescription}
        status={status}
      />
    );
  }

  const loadingElement = (
    <CarbonLoading
      description={resolvedDescription}
      withOverlay={false}
    />
  );

  if (centered) {
    return (
      <div className={styles.centeredContainer}>
        {loadingElement}
      </div>
    );
  }

  return loadingElement;
}
