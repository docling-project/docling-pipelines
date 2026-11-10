import React from 'react';
import { PermissionTooltip } from './PermissionTooltip';

/** Props accepted by {@link PermissionButtonElement}. */
type PermissionButtonElementProps = React.ButtonHTMLAttributes<HTMLButtonElement> & {
  /** Why the button is disabled. When empty the plain button is rendered. */
  permissionReason?: string | null;
};

/**
 * Button element for Carbon's polymorphic `as` prop that explains why it is disabled.
 *
 * Needed where Carbon renders the button itself (for example the action of an
 * empty state), so a tooltip cannot be wrapped around it from the outside:
 * `{ ...action, as: PermissionButtonElement, permissionReason }`.
 */
export const PermissionButtonElement = React.forwardRef<HTMLButtonElement, PermissionButtonElementProps>(
  ({ permissionReason, ...rest }, ref) => (
    <PermissionTooltip reason={permissionReason}>
      {/* Carbon passes its computed button props through `as`; they must reach the DOM node. */}
      {/* eslint-disable-next-line react/jsx-props-no-spreading */}
      <button ref={ref} {...rest} />
    </PermissionTooltip>
  )
);
PermissionButtonElement.displayName = 'PermissionButtonElement';
