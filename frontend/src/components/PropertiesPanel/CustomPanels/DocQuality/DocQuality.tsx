/**
 * @file DocQuality properties panel body.
 *
 * The `doc_quality` operator has no user-configurable attributes.
 */

import React from 'react';
import { InlineNotification } from '@carbon/react';
import { useIntl } from 'react-intl';
import { messages } from './DocQuality.messages';

interface DocQualityPanelBodyProps {
  controller: any;
}

export function DocQualityPanelBody({ controller: _controller }: DocQualityPanelBodyProps): React.JSX.Element {
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
