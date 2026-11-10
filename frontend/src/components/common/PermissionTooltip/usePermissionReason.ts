import { useIntl } from 'react-intl';
import { useAuth } from '@/hooks/useAuth';
import { messages } from './PermissionTooltip.messages';

/** Return shape of {@link usePermissionReason}. */
export interface UsePermissionReasonReturn {
  /** `true` when the user holds `editor` or `admin`. */
  canEdit: boolean;
  /** `true` when the user may modify an asset created by `createdBy`. */
  canModifyAsset: (createdBy?: string | null) => boolean;
  /** Why creating is disabled, or `null` when it is allowed. */
  createReason: string | null;
  /** Why modifying an asset created by `createdBy` is disabled, or `null` when it is allowed. */
  getModifyReason: (createdBy?: string | null) => string | null;
}

/**
 * Resolves the localized tooltip text that explains a disabled create, edit or
 * delete action. The text is `null` when the action is allowed.
 *
 * The UI gating is a convenience only: the backend enforces every permission.
 */
export function usePermissionReason(): UsePermissionReasonReturn {
  const intl = useIntl();
  const { canEdit, canModifyAsset } = useAuth();

  const createReason = canEdit ? null : intl.formatMessage(messages.needEditor);

  const getModifyReason = (createdBy?: string | null): string | null => {
    if (!canEdit) { return intl.formatMessage(messages.needEditor); }
    if (!canModifyAsset(createdBy)) { return intl.formatMessage(messages.needOwner); }
    return null;
  };

  return { canEdit, canModifyAsset, createReason, getModifyReason };
}
