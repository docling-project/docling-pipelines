import React, { type ElementType } from 'react';
import { Button } from '@carbon/react';
import { NoDataEmptyState } from '@carbon/ibm-products';
import type { CarbonIconType } from '@carbon/icons-react';
import { PermissionTooltip, PermissionButtonElement } from '@/components/common/PermissionTooltip';
import styles from './HomeCard.module.scss';

/**
 * Describes an optional call-to-action button rendered inside the empty state.
 */
interface HomeCardAction {
  text: string;
  kind?: 'primary' | 'secondary' | 'tertiary';
  renderIcon?: CarbonIconType;
  onClick?: () => void;
  /** Disables the CTA. */
  disabled?: boolean;
  /** Tooltip explaining why the CTA is disabled. Shown only when `disabled` is true. */
  disabledReason?: string;
}

/**
 * Props for {@link HomeCard}.
 */
interface HomeCardProps {
  /** Card heading */
  title: string;
  /** Carbon icon component rendered in the 48×48 header action slot */
  headerIcon: ElementType;
  /** Accessible label for the header icon button */
  headerIconDescription: string;
  /** Called when the header icon button is clicked */
  onHeaderAction?: () => void;
  /** Disables the header icon button. */
  headerActionDisabled?: boolean;
  /** Tooltip explaining why the header icon button is disabled. */
  headerActionDisabledReason?: string;
  /** Empty state heading */
  emptyTitle: string;
  /** Empty state sub-text */
  emptySubtitle: string;
  /** Optional CTA rendered inside the empty state */
  emptyAction?: HomeCardAction;
  /** `flex:2` (double width) when true, `flex:1` otherwise */
  wide?: boolean;
  /**
   * When provided, renders these rows instead of the empty state.
   * The empty state is shown only when `children` is absent or null.
   */
  children?: React.ReactNode;
}

/**
 * Reusable summary card used on the Home page.
 *
 * - Header: fixed 48px row with a title and a single ghost icon-button action slot.
 * - Body: renders `children` when provided; falls back to a `NoDataEmptyState` otherwise.
 * - Width: `flex:2` (double) when `wide=true`, `flex:1` (equal) otherwise.
 * - Card height is content-driven — no fixed min-height when data is present.
 */
export function HomeCard({
  title,
  headerIcon,
  headerIconDescription,
  onHeaderAction,
  headerActionDisabled = false,
  headerActionDisabledReason,
  emptyTitle,
  emptySubtitle,
  emptyAction,
  wide = false,
  children,
}: HomeCardProps): React.JSX.Element {
  return (
    <div className={wide ? styles.cardWide : styles.card}>
      <div className={styles.cardHeader}>
        <span className={styles.cardTitle}>{title}</span>
        <div className={styles.cardHeaderAction}>
          <PermissionTooltip reason={headerActionDisabled ? headerActionDisabledReason : null} align="left">
            <Button
              kind="ghost"
              size="sm"
              renderIcon={headerIcon}
              iconDescription={headerIconDescription}
              hasIconOnly
              disabled={headerActionDisabled}
              onClick={onHeaderAction}
            />
          </PermissionTooltip>
        </div>
      </div>

      <div className={styles.cardBody}>
        {children ?? (
          <div className={styles.emptyStateWrapper}>
            <NoDataEmptyState
              title={emptyTitle}
              subtitle={emptySubtitle}
              size="sm"
              action={emptyAction && {
                text: emptyAction.text,
                kind: emptyAction.kind,
                renderIcon: emptyAction.renderIcon,
                onClick: emptyAction.onClick,
                ...(emptyAction.disabled && {
                  disabled: true,
                  as: PermissionButtonElement,
                  permissionReason: emptyAction.disabledReason,
                }),
              }}
            />
          </div>
        )}
      </div>
    </div>
  );
}
