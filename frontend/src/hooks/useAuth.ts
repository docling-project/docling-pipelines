/**
 * Authentication hook backed by the `auth` Redux slice.
 *
 * Exposes the current user and the permission flags used to gate UI actions.
 * The gating is a convenience only: the backend enforces every permission.
 */

import { useCallback } from 'react';
import type { AuthUser } from '@/types';
import { selectAuthEnabled, selectAuthStatus, selectAuthUser } from '@/selectors';
import { useAppSelector } from './useAppSelector';

/** Return shape of {@link useAuth}. */
export interface UseAuthReturn {
  /** The signed-in user, or `null`. */
  user: AuthUser | null;
  /** `false` when the backend reports that authentication is disabled. */
  authEnabled: boolean;
  /** `true` when the current user has a valid session (or auth is disabled). */
  isAuthenticated: boolean;
  /** `true` while the auth state is `idle` or `loading`. */
  isLoading: boolean;
  /** `true` for `editor` or `admin`. */
  canEdit: boolean;
  /** `true` for `admin`. */
  canAdmin: boolean;
  /**
   * `true` when the user may modify an asset created by `createdBy`:
   * admins always, editors when `createdBy` is empty or their own username.
   */
  canModifyAsset: (createdBy?: string | null) => boolean;
}

/**
 * Returns the current authentication state and permission flags.
 *
 * Used by {@link ProtectedRoute} and by components that gate actions by role.
 */
export function useAuth(): UseAuthReturn {
  const user = useAppSelector(selectAuthUser);
  const authEnabled = useAppSelector(selectAuthEnabled);
  const status = useAppSelector(selectAuthStatus);

  const roles = user?.roles ?? [];
  const canAdmin = roles.includes('admin');
  const canEdit = canAdmin || roles.includes('editor');

  const canModifyAsset = useCallback(
    (createdBy?: string | null): boolean => {
      if (canAdmin) { return true; }
      if (!canEdit) { return false; }
      return !createdBy || createdBy === user?.username;
    },
    [canAdmin, canEdit, user?.username]
  );

  return {
    user,
    authEnabled,
    isAuthenticated: status === 'authenticated',
    isLoading: status === 'idle' || status === 'loading',
    canEdit,
    canAdmin,
    canModifyAsset,
  };
}
