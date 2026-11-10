import React from 'react';
import { Tooltip } from '@carbon/react';
import styles from './PermissionTooltip.module.scss';

/** Props for {@link PermissionTooltip}. */
interface PermissionTooltipProps {
  /**
   * Why the wrapped control is disabled. When empty or `null` the control is
   * rendered unchanged; otherwise it is wrapped in a Carbon tooltip.
   */
  readonly reason: string | null | undefined;
  /** The (already disabled) control to explain. */
  readonly children: React.ReactNode;
  /** Tooltip alignment. */
  readonly align?: React.ComponentProps<typeof Tooltip>['align'];
}

/**
 * Explains why a control is disabled for the current user.
 *
 * Disabled buttons do not emit pointer or focus events, so the control is wrapped
 * in a focusable element that carries the Carbon tooltip. The tooltip text is
 * exposed through `aria-describedby`.
 */
export function PermissionTooltip({
  reason,
  children,
  align = 'top',
}: PermissionTooltipProps): React.JSX.Element {
  if (!reason) {
    return <>{children}</>;
  }
  return (
    <Tooltip description={reason} align={align}>
      <span className={styles.trigger} tabIndex={0}>{children}</span>
    </Tooltip>
  );
}
