/**
 * @file Weaviate connection controls for the VectorDB panel.
 *
 * Stateless: renders the connection type selector and the controls of the active
 * connection type from the parsed `provider_config`, and reports each change as a
 * complete next `provider_config` so a switch is a single atomic write. Validation
 * results arrive as an error map; this component only displays them.
 */

import React from 'react';
import { useIntl } from 'react-intl';
import { Dropdown, InlineNotification, TextInput, Toggle } from '@carbon/react';
import type { MessageDescriptor } from 'react-intl';
import { messages, weaviateErrorMessages } from './VectorDB.messages';
import {
  WEAVIATE_CONNECTION_TYPES,
  WEAVIATE_DEFAULTS,
  WEAVIATE_FIELD_IDS,
  applyGrpcOverride,
  getConnectionType,
  getHttpSecure,
  hasTlsError,
  switchConnectionType,
} from './vectordb-weaviate';
import type { WeaviateConnectionType, WeaviateErrors, WeaviateField } from './vectordb-weaviate';
import common from '../../CommonPropertiesPanel.module.scss';

export interface WeaviateFieldsProps {
  /** Parsed saved `provider_config`. */
  config: Record<string, unknown>;
  /** Errors to display (the parent decides when a field's error becomes visible). */
  errors: WeaviateErrors;
  /** Receives the complete next `provider_config`. */
  onChange: (next: Record<string, unknown>) => void;
}

const CONNECTION_TYPE_LABELS: Record<WeaviateConnectionType, MessageDescriptor> = {
  [WEAVIATE_CONNECTION_TYPES.ON_PREM]: messages.weaviateConnectionOnPrem,
  [WEAVIATE_CONNECTION_TYPES.CLOUD]: messages.weaviateConnectionCloud,
};

/** Selection states of the gRPC TLS dropdown; `inherit` leaves `grpc_secure` unset. */
const GRPC_TLS_OPTIONS = ['inherit', 'on', 'off'] as const;
type GrpcTlsOption = (typeof GRPC_TLS_OPTIONS)[number];

const GRPC_TLS_LABELS: Record<GrpcTlsOption, MessageDescriptor> = {
  inherit: messages.weaviateGrpcTlsInherit,
  on: messages.on,
  off: messages.off,
};

const TLS_ALERT_ID = 'weaviate-tls-alert';

/** Port text becomes a number when numeric; anything else is kept so validation can reject it. */
function parsePort(text: string): number | string {
  const parsed = Number(text);
  return text.trim() !== '' && Number.isInteger(parsed) ? parsed : text;
}

export function WeaviateConnectionFields({
  config,
  errors,
  onChange,
}: WeaviateFieldsProps): React.JSX.Element {
  const intl = useIntl();
  const connectionType = getConnectionType(config);

  const errorText = (field: WeaviateField): string | undefined => {
    const code = errors[field];
    return code ? intl.formatMessage(weaviateErrorMessages[code]) : undefined;
  };

  const setField = (key: string, value: unknown): void => {
    onChange({ ...config, [key]: value });
  };

  const grpcTlsSelection: GrpcTlsOption =
    typeof config['grpc_secure'] !== 'boolean' ? 'inherit' : config['grpc_secure'] ? 'on' : 'off';

  const renderPortInput = (field: 'port' | 'grpc_port', label: MessageDescriptor, fallback: number): React.JSX.Element => (
    <div className={common.formField}>
      <TextInput
        id={WEAVIATE_FIELD_IDS[field]}
        labelText={intl.formatMessage(label)}
        value={String(config[field] ?? fallback)}
        onChange={(e: React.ChangeEvent<HTMLInputElement>) => {
          setField(field, parsePort(e.target.value));
        }}
        invalid={errors[field] !== undefined}
        invalidText={errorText(field)}
        placeholder={String(fallback)}
      />
    </div>
  );

  return (
    <div className={common.accordionContent}>
      <div className={common.formField}>
        <Dropdown
          id="weaviate-connection-type"
          label={intl.formatMessage(messages.weaviateSelectConnectionType)}
          titleText={intl.formatMessage(messages.weaviateConnectionType)}
          items={Object.values(WEAVIATE_CONNECTION_TYPES)}
          itemToString={(item: WeaviateConnectionType | null) =>
            item ? intl.formatMessage(CONNECTION_TYPE_LABELS[item]) : ''
          }
          selectedItem={connectionType}
          onChange={({ selectedItem }: { selectedItem?: WeaviateConnectionType | null }) => {
            if (selectedItem) {
              onChange(switchConnectionType(config, selectedItem));
            }
          }}
        />
      </div>

      {connectionType === WEAVIATE_CONNECTION_TYPES.CLOUD && (
        <div className={common.formField}>
          <TextInput
            id={WEAVIATE_FIELD_IDS.cluster_url}
            labelText={intl.formatMessage(messages.weaviateClusterUrl)}
            value={typeof config['cluster_url'] === 'string' ? config['cluster_url'] : ''}
            onChange={(e: React.ChangeEvent<HTMLInputElement>) => {
              setField('cluster_url', e.target.value);
            }}
            invalid={errors.cluster_url !== undefined}
            invalidText={errorText('cluster_url')}
            placeholder="https://my-cluster.weaviate.cloud"
          />
        </div>
      )}

      {connectionType === WEAVIATE_CONNECTION_TYPES.ON_PREM && (
        <>
          <div className={common.formField}>
            <TextInput
              id={WEAVIATE_FIELD_IDS.host}
              labelText={intl.formatMessage(messages.host)}
              value={typeof config['host'] === 'string' ? config['host'] : WEAVIATE_DEFAULTS.HOST}
              onChange={(e: React.ChangeEvent<HTMLInputElement>) => {
                setField('host', e.target.value);
              }}
              invalid={errors.host !== undefined}
              invalidText={errorText('host')}
              placeholder={WEAVIATE_DEFAULTS.HOST}
            />
          </div>
          {renderPortInput('port', messages.weaviateHttpPort, WEAVIATE_DEFAULTS.PORT)}
          <div className={common.formField}>
            <Toggle
              id={WEAVIATE_FIELD_IDS.secure}
              labelText={intl.formatMessage(messages.weaviateHttpTls)}
              labelA={intl.formatMessage(messages.off)}
              labelB={intl.formatMessage(messages.on)}
              toggled={getHttpSecure(config)}
              onToggle={(checked: boolean) => {
                setField('secure', checked);
              }}
              aria-invalid={errors.secure !== undefined}
              aria-describedby={errors.secure ? TLS_ALERT_ID : undefined}
            />
          </div>
          <div className={common.formField}>
            <TextInput
              id="weaviate-grpc-host"
              labelText={intl.formatMessage(messages.weaviateGrpcHost)}
              helperText={intl.formatMessage(messages.weaviateGrpcHostHelper)}
              value={typeof config['grpc_host'] === 'string' ? config['grpc_host'] : ''}
              onChange={(e: React.ChangeEvent<HTMLInputElement>) => {
                onChange(applyGrpcOverride(config, 'grpc_host', e.target.value));
              }}
            />
          </div>
          {renderPortInput('grpc_port', messages.weaviateGrpcPort, WEAVIATE_DEFAULTS.GRPC_PORT)}
          <div className={common.formField}>
            <Dropdown
              id={WEAVIATE_FIELD_IDS.grpc_secure}
              label={intl.formatMessage(messages.weaviateSelectGrpcTls)}
              titleText={intl.formatMessage(messages.weaviateGrpcTls)}
              items={[...GRPC_TLS_OPTIONS]}
              itemToString={(item: GrpcTlsOption | null) =>
                item ? intl.formatMessage(GRPC_TLS_LABELS[item]) : ''
              }
              selectedItem={grpcTlsSelection}
              onChange={({ selectedItem }: { selectedItem?: GrpcTlsOption | null }) => {
                if (selectedItem) {
                  onChange(
                    applyGrpcOverride(config, 'grpc_secure', selectedItem === 'inherit' ? null : selectedItem === 'on')
                  );
                }
              }}
              invalid={errors.grpc_secure !== undefined}
              invalidText={errorText('grpc_secure')}
            />
          </div>
          {hasTlsError(errors) && (
            <div id={TLS_ALERT_ID} className={common.formField}>
              <InlineNotification
                kind="error"
                role="alert"
                title={intl.formatMessage(messages.weaviateTlsAlertTitle)}
                subtitle={intl.formatMessage(messages.weaviateTlsAlert)}
                lowContrast
                hideCloseButton
              />
            </div>
          )}
        </>
      )}
    </div>
  );
}
