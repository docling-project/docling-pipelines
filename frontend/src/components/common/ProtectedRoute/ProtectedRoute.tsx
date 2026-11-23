import React from 'react';
import { useIntl } from 'react-intl';
import { Navigate, useLocation } from 'react-router-dom';
import { Button, InlineNotification } from '@carbon/react';
import { useAppDispatch } from '@/hooks/useAppDispatch';
import { useAuth } from '@/hooks/useAuth';
import { bootstrapAuth } from '@/slices/authSlice';
import { Loading } from '../Loading';
import { messages } from './ProtectedRoute.messages';
import styles from './ProtectedRoute.module.scss';

/**
 * Props for {@link ProtectedRoute}.
 */
interface ProtectedRouteProps {
  /** The route subtree to render when the user is authenticated. */
  children: React.ReactNode;
}

/**
 * Route guard that checks authentication before rendering its children.
 *
 * - While the auth state is being resolved, renders a full-page `Loading` spinner.
 * - If bootstrapping auth failed (5xx or network error), fails closed and renders
 *   an accessible service-unavailable error state with a Retry button.
 * - If the user is not authenticated, redirects to `/login` and preserves the
 *   attempted location in the `?return_to=` query parameter so the login page can
 *   redirect back after a successful sign-in.
 * - If the user is authenticated, renders `children` unchanged.
 */
export function ProtectedRoute({ children }: ProtectedRouteProps): React.JSX.Element {
  const intl = useIntl();
  const dispatch = useAppDispatch();
  const { isAuthenticated, isLoading, isError } = useAuth();
  const location = useLocation();

  if (isLoading) {
    return <Loading description={intl.formatMessage(messages.checkingAuth)} />;
  }

  if (isError) {
    return (
      <main className={styles.errorContainer}>
        <InlineNotification
          kind="error"
          title={intl.formatMessage(messages.authUnavailableTitle)}
          subtitle={intl.formatMessage(messages.authUnavailableSubtitle)}
          hideCloseButton
          lowContrast
          role="alert"
        />
        <Button kind="primary" onClick={() => { void dispatch(bootstrapAuth()); }}>
          {intl.formatMessage(messages.retry)}
        </Button>
      </main>
    );
  }

  if (!isAuthenticated) {
    const returnTo = encodeURIComponent(location.pathname + location.search);
    return <Navigate to={`/login?return_to=${returnTo}`} replace />;
  }

  return <>{children}</>;
}
