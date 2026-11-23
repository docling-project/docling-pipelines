/**
 * @file Weaviate authentication controls for the VectorDB panel.
 *
 * Stateless: renders the authentication method selector and only the credential
 * inputs of the selected method. A method switch is reported as one complete next
 * `provider_config` with the previous method's credentials removed.
 */

import React from 'react';
import { useIntl } from 'react-intl';
import { Dropdown } from '@carbon/react';
import type { MessageDescriptor } from 'react-intl';
import { VaultInput } from '@/components/common';
import { messages, weaviateErrorMessages } from './VectorDB.messages';
import {
  WEAVIATE_AUTH_TYPES,
  WEAVIATE_FIELD_IDS,
  getAuthType,
  switchAuthType,
} from './vectordb-weaviate';
import type { WeaviateAuthType, WeaviateField } from './vectordb-weaviate';
import type { WeaviateFieldsProps } from './WeaviateConnectionFields';
import common from '../../CommonPropertiesPanel.module.scss';

const AUTH_TYPE_LABELS: Record<WeaviateAuthType, MessageDescriptor> = {
  [WEAVIATE_AUTH_TYPES.NONE]: messages.authNone,
  [WEAVIATE_AUTH_TYPES.API_KEY]: messages.weaviateAuthApiKey,
  [WEAVIATE_AUTH_TYPES.BEARER_TOKEN]: messages.weaviateAuthBearerToken,
  [WEAVIATE_AUTH_TYPES.CLIENT_PASSWORD]: messages.weaviateAuthClientPassword,
};

export function WeaviateAuthFields({ config, errors, onChange }: WeaviateFieldsProps): React.JSX.Element {
  const intl = useIntl();
  const authType = getAuthType(config);

  const errorText = (field: WeaviateField): string | undefined => {
    const code = errors[field];
    return code ? intl.formatMessage(weaviateErrorMessages[code]) : undefined;
  };

  const textValue = (key: string): string => (typeof config[key] === 'string' ? config[key] : '');

  const renderSecretInput = (
    field: 'api_key' | 'bearer_token' | 'username' | 'password',
    label: MessageDescriptor,
    masked = true
  ): React.JSX.Element => (
    <div className={common.formField}>
      <VaultInput
        id={WEAVIATE_FIELD_IDS[field]}
        labelText={intl.formatMessage(label)}
        value={textValue(field)}
        masked={masked}
        onChange={(value: string) => {
          onChange({ ...config, [field]: value });
        }}
        invalid={errors[field] !== undefined}
        invalidText={errorText(field)}
      />
    </div>
  );

  return (
    <div className={common.accordionContent}>
      <div className={common.formField}>
        <Dropdown
          id="weaviate-auth-type"
          label={intl.formatMessage(messages.selectMethod)}
          titleText={intl.formatMessage(messages.authMethod)}
          items={Object.values(WEAVIATE_AUTH_TYPES)}
          itemToString={(item: WeaviateAuthType | null) =>
            item ? intl.formatMessage(AUTH_TYPE_LABELS[item]) : ''
          }
          selectedItem={authType}
          onChange={({ selectedItem }: { selectedItem?: WeaviateAuthType | null }) => {
            if (selectedItem) {
              onChange(switchAuthType(config, selectedItem));
            }
          }}
        />
      </div>

      {authType === WEAVIATE_AUTH_TYPES.API_KEY &&
        renderSecretInput('api_key', messages.weaviateAuthApiKey)}

      {authType === WEAVIATE_AUTH_TYPES.BEARER_TOKEN &&
        renderSecretInput('bearer_token', messages.weaviateAuthBearerToken)}

      {authType === WEAVIATE_AUTH_TYPES.CLIENT_PASSWORD && (
        <>
          {renderSecretInput('username', messages.username, false)}
          {renderSecretInput('password', messages.password)}
        </>
      )}
    </div>
  );
}
