/**
 * @file De-duplicator operator configuration panel body.
 *
 * The `ededup` operator has no user-configurable attributes — it automatically
 * removes exact duplicate documents based on a content hash. This panel renders
 * an informational message explaining that behaviour.
 */

import React from 'react';
import { InlineNotification } from '@carbon/react';
import { useIntl } from 'react-intl';
import { messages } from './Ededup.messages';

interface EdedupPanelBodyProps {
  controller: any;
}

// controller is required by the OPERATOR_PANEL_MAP signature but unused here

export function EdedupPanelBody({ controller: _controller }: EdedupPanelBodyProps): React.JSX.Element {
  const intl = useIntl();
  return (
    <InlineNotification
      kind="info"
      title={intl.formatMessage(messages.title)}
      subtitle={intl.formatMessage(messages.subtitle)}
      lowContrast
      hideCloseButton
    />
  );
}
