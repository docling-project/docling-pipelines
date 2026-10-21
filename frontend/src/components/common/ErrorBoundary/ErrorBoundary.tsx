import React, { Component, type ReactNode, type ErrorInfo } from 'react';
import { ErrorEmptyState } from '@carbon/ibm-products';
import { Renew } from '@carbon/icons-react';
import { useIntl } from 'react-intl';
import { log4js, logUtil } from '@/utils/logger';
import { useTheme } from '@/hooks';
import { messages } from './ErrorBoundary.messages';
import styles from './ErrorBoundary.module.scss';

const logger = log4js.getLogger('ErrorBoundary');

/** Props passed from ErrorBoundary to the default fallback UI. */
interface ErrorFallbackProps {
  message: string | undefined;
  errorInfo: ErrorInfo | null;
  onReset: () => void;
}

/**
 * Functional component so it can call useTheme() for illustrationTheme.
 * Rendered by ErrorBoundary when no custom fallback is provided.
 */
function ErrorFallback({ message, errorInfo, onReset }: ErrorFallbackProps): React.JSX.Element {
  const { isDarkMode } = useTheme();
  const intl = useIntl();
  return (
    <div className={styles.errorContainer}>
      <ErrorEmptyState
        illustrationTheme={isDarkMode ? 'dark' : 'light'}
        title={intl.formatMessage(messages.title)}
        subtitle={message ?? intl.formatMessage(messages.unexpectedError)}
        action={{
          text: intl.formatMessage(messages.tryAgain),
          onClick: onReset,
          renderIcon: Renew,
          kind: 'tertiary',
        }}
      />
      {import.meta.env.DEV && errorInfo && (
        <details className={styles.errorDetails}>
          <summary>{intl.formatMessage(messages.errorDetails)}</summary>
          <pre className={styles.errorStack}>
            {errorInfo.componentStack}
          </pre>
        </details>
      )}
    </div>
  );
}

interface ErrorBoundaryProps {
  children: ReactNode;
  fallback?: ReactNode;
}

interface ErrorBoundaryState {
  hasError: boolean;
  error: Error | null;
  errorInfo: ErrorInfo | null;
}

/**
 * Error boundary component that catches JavaScript errors anywhere in the child component tree
 * and displays a fallback UI instead of crashing the entire application.
 */
export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  constructor(props: ErrorBoundaryProps) {
    super(props);
    this.state = {
      hasError: false,
      error: null,
      errorInfo: null,
    };
  }

  static getDerivedStateFromError(error: Error): Partial<ErrorBoundaryState> {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo): void {
    logUtil.error({ logger, message: 'ErrorBoundary caught an error', data: { error, errorInfo } });
    this.setState({ error, errorInfo });
  }

  handleReset = (): void => {
    this.setState({ hasError: false, error: null, errorInfo: null });
  };

  render(): ReactNode {
    if (this.state.hasError) {
      if (this.props.fallback) {
        return this.props.fallback;
      }
      return (
        <ErrorFallback
          message={this.state.error?.message}
          errorInfo={this.state.errorInfo}
          onReset={this.handleReset}
        />
      );
    }
    return this.props.children;
  }
}
