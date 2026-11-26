import { defineMessages } from 'react-intl';
import type { MessageDescriptor } from 'react-intl';
import type { WeaviateFieldError } from './vectordb-weaviate';

export const messages = defineMessages({
  featureMappingTitle: {
    id: 'src.components.PropertiesPanel.CustomPanels.VectorDB.featureMappingTitle',
    defaultMessage: 'Map features to resource columns',
  },
  featureMappingDesc: {
    id: 'src.components.PropertiesPanel.CustomPanels.VectorDB.featureMappingDesc',
    defaultMessage: 'Select features from connected nodes and add them to your target resource columns',
  },
  addFeatureMappings: {
    id: 'src.components.PropertiesPanel.CustomPanels.VectorDB.addFeatureMappings',
    defaultMessage: 'Add feature mappings',
  },
  provider: {
    id: 'src.components.PropertiesPanel.CustomPanels.VectorDB.provider',
    defaultMessage: 'Provider',
  },
  selectProvider: {
    id: 'src.components.PropertiesPanel.CustomPanels.VectorDB.selectProvider',
    defaultMessage: 'Select provider',
  },
  connectionTitle: {
    id: 'src.components.PropertiesPanel.CustomPanels.VectorDB.connectionTitle',
    defaultMessage: 'Connection',
  },
  authenticationTitle: {
    id: 'src.components.PropertiesPanel.CustomPanels.VectorDB.authenticationTitle',
    defaultMessage: 'Authentication',
  },
  advancedTitle: {
    id: 'src.components.PropertiesPanel.CustomPanels.VectorDB.advancedTitle',
    defaultMessage: 'Advanced',
  },
  host: {
    id: 'src.components.PropertiesPanel.CustomPanels.VectorDB.host',
    defaultMessage: 'Host',
  },
  port: {
    id: 'src.components.PropertiesPanel.CustomPanels.VectorDB.port',
    defaultMessage: 'Port',
  },
  useSsl: {
    id: 'src.components.PropertiesPanel.CustomPanels.VectorDB.useSsl',
    defaultMessage: 'Use SSL/TLS',
  },
  verifySslCerts: {
    id: 'src.components.PropertiesPanel.CustomPanels.VectorDB.verifySslCerts',
    defaultMessage: 'Verify SSL Certificates',
  },
  off: {
    id: 'src.components.PropertiesPanel.CustomPanels.VectorDB.off',
    defaultMessage: 'Off',
  },
  on: {
    id: 'src.components.PropertiesPanel.CustomPanels.VectorDB.on',
    defaultMessage: 'On',
  },
  databaseName: {
    id: 'src.components.PropertiesPanel.CustomPanels.VectorDB.databaseName',
    defaultMessage: 'Database Name',
  },
  secureTls: {
    id: 'src.components.PropertiesPanel.CustomPanels.VectorDB.secureTls',
    defaultMessage: 'Secure (TLS/SSL)',
  },
  authMethod: {
    id: 'src.components.PropertiesPanel.CustomPanels.VectorDB.authMethod',
    defaultMessage: 'Authentication method',
  },
  selectMethod: {
    id: 'src.components.PropertiesPanel.CustomPanels.VectorDB.selectMethod',
    defaultMessage: 'Select method',
  },
  authNone: {
    id: 'src.components.PropertiesPanel.CustomPanels.VectorDB.authNone',
    defaultMessage: 'None',
  },
  authBasic: {
    id: 'src.components.PropertiesPanel.CustomPanels.VectorDB.authBasic',
    defaultMessage: 'Basic (username / password)',
  },
  authJwt: {
    id: 'src.components.PropertiesPanel.CustomPanels.VectorDB.authJwt',
    defaultMessage: 'JWT token',
  },
  authAws: {
    id: 'src.components.PropertiesPanel.CustomPanels.VectorDB.authAws',
    defaultMessage: 'AWS IAM',
  },
  username: {
    id: 'src.components.PropertiesPanel.CustomPanels.VectorDB.username',
    defaultMessage: 'Username',
  },
  password: {
    id: 'src.components.PropertiesPanel.CustomPanels.VectorDB.password',
    defaultMessage: 'Password',
  },
  jwtToken: {
    id: 'src.components.PropertiesPanel.CustomPanels.VectorDB.jwtToken',
    defaultMessage: 'JWT Token',
  },
  awsRegion: {
    id: 'src.components.PropertiesPanel.CustomPanels.VectorDB.awsRegion',
    defaultMessage: 'AWS Region',
  },
  authType: {
    id: 'src.components.PropertiesPanel.CustomPanels.VectorDB.authType',
    defaultMessage: 'Auth Type',
  },
  selectAuthType: {
    id: 'src.components.PropertiesPanel.CustomPanels.VectorDB.selectAuthType',
    defaultMessage: 'Select auth type',
  },
  passwordTooltip: {
    id: 'src.components.PropertiesPanel.CustomPanels.VectorDB.passwordTooltip',
    defaultMessage: 'Password for password-based authentication.',
  },
  token: {
    id: 'src.components.PropertiesPanel.CustomPanels.VectorDB.token',
    defaultMessage: 'Token',
  },
  tokenTooltip: {
    id: 'src.components.PropertiesPanel.CustomPanels.VectorDB.tokenTooltip',
    defaultMessage: 'API token for Milvus cloud or wx.data deployments.',
  },
  uri: {
    id: 'src.components.PropertiesPanel.CustomPanels.VectorDB.uri',
    defaultMessage: 'URI',
  },
  additionalConfig: {
    id: 'src.components.PropertiesPanel.CustomPanels.VectorDB.additionalConfig',
    defaultMessage: 'Additional configuration (JSON)',
  },
  additionalConfigHelperText: {
    id: 'src.components.PropertiesPanel.CustomPanels.VectorDB.additionalConfigHelperText',
    defaultMessage: 'Extra provider-specific options not covered above',
  },
  additionalConfigInvalid: {
    id: 'src.components.PropertiesPanel.CustomPanels.VectorDB.additionalConfigInvalid',
    defaultMessage: 'Must be a valid JSON object',
  },
  errorTitle: {
    id: 'src.components.PropertiesPanel.CustomPanels.VectorDB.errorTitle',
    defaultMessage: 'Error',
  },
  advancedConfigInvalidError: {
    id: 'src.components.PropertiesPanel.CustomPanels.VectorDB.advancedConfigInvalidError',
    defaultMessage: 'Advanced JSON configuration must be a valid JSON object before opening feature mappings.',
  },
  milvusLiteBinaryWarningTitle: {
    id: 'src.components.PropertiesPanel.CustomPanels.VectorDB.milvusLiteBinaryWarningTitle',
    defaultMessage: 'Milvus Lite restriction',
  },
  milvusLiteBinaryWarning: {
    id: 'src.components.PropertiesPanel.CustomPanels.VectorDB.milvusLiteBinaryWarning',
    defaultMessage:
      'Milvus Lite does not support binary vectors. Use standalone, grpc, or uri deployments for binary vector indexes, or set Quantization to "None" in the upstream Embeddings operator.',
  },
  openSearchBinaryWarningTitle: {
    id: 'src.components.PropertiesPanel.CustomPanels.VectorDB.openSearchBinaryWarningTitle',
    defaultMessage: 'OpenSearch restriction',
  },
  openSearchBinaryWarning: {
    id: 'src.components.PropertiesPanel.CustomPanels.VectorDB.openSearchBinaryWarning',
    defaultMessage:
      'OpenSearch does not support binary vectors. Use a provider that supports binary vectors (such as Milvus), or set Quantization to "None" in the upstream Embeddings operator.',
  },
  weaviateConnectionType: {
    id: 'src.components.PropertiesPanel.CustomPanels.VectorDB.weaviateConnectionType',
    defaultMessage: 'Connection type',
  },
  weaviateSelectConnectionType: {
    id: 'src.components.PropertiesPanel.CustomPanels.VectorDB.weaviateSelectConnectionType',
    defaultMessage: 'Select connection type',
  },
  weaviateConnectionOnPrem: {
    id: 'src.components.PropertiesPanel.CustomPanels.VectorDB.weaviateConnectionOnPrem',
    defaultMessage: 'On-premises',
  },
  weaviateConnectionCloud: {
    id: 'src.components.PropertiesPanel.CustomPanels.VectorDB.weaviateConnectionCloud',
    defaultMessage: 'Weaviate Cloud',
  },
  weaviateClusterUrl: {
    id: 'src.components.PropertiesPanel.CustomPanels.VectorDB.weaviateClusterUrl',
    defaultMessage: 'Cluster URL',
  },
  weaviateHttpPort: {
    id: 'src.components.PropertiesPanel.CustomPanels.VectorDB.weaviateHttpPort',
    defaultMessage: 'HTTP port',
  },
  weaviateHttpTls: {
    id: 'src.components.PropertiesPanel.CustomPanels.VectorDB.weaviateHttpTls',
    defaultMessage: 'HTTP TLS',
  },
  weaviateGrpcHost: {
    id: 'src.components.PropertiesPanel.CustomPanels.VectorDB.weaviateGrpcHost',
    defaultMessage: 'gRPC host',
  },
  weaviateGrpcHostHelper: {
    id: 'src.components.PropertiesPanel.CustomPanels.VectorDB.weaviateGrpcHostHelper',
    defaultMessage: 'Leave empty to use the host above',
  },
  weaviateGrpcPort: {
    id: 'src.components.PropertiesPanel.CustomPanels.VectorDB.weaviateGrpcPort',
    defaultMessage: 'gRPC port',
  },
  weaviateGrpcTls: {
    id: 'src.components.PropertiesPanel.CustomPanels.VectorDB.weaviateGrpcTls',
    defaultMessage: 'gRPC TLS',
  },
  weaviateSelectGrpcTls: {
    id: 'src.components.PropertiesPanel.CustomPanels.VectorDB.weaviateSelectGrpcTls',
    defaultMessage: 'Select gRPC TLS setting',
  },
  weaviateGrpcTlsInherit: {
    id: 'src.components.PropertiesPanel.CustomPanels.VectorDB.weaviateGrpcTlsInherit',
    defaultMessage: 'Same as HTTP',
  },
  weaviateTlsAlertTitle: {
    id: 'src.components.PropertiesPanel.CustomPanels.VectorDB.weaviateTlsAlertTitle',
    defaultMessage: 'TLS required',
  },
  weaviateTlsAlert: {
    id: 'src.components.PropertiesPanel.CustomPanels.VectorDB.weaviateTlsAlert',
    defaultMessage:
      'Both HTTP and gRPC must use TLS when authentication is configured. Credentials must not be sent over an unencrypted connection.',
  },
  weaviateAuthApiKey: {
    id: 'src.components.PropertiesPanel.CustomPanels.VectorDB.weaviateAuthApiKey',
    defaultMessage: 'API key',
  },
  weaviateAuthBearerToken: {
    id: 'src.components.PropertiesPanel.CustomPanels.VectorDB.weaviateAuthBearerToken',
    defaultMessage: 'Bearer token',
  },
  weaviateAuthClientPassword: {
    id: 'src.components.PropertiesPanel.CustomPanels.VectorDB.weaviateAuthClientPassword',
    defaultMessage: 'Username and password',
  },
  weaviateErrorRequired: {
    id: 'src.components.PropertiesPanel.CustomPanels.VectorDB.weaviateErrorRequired',
    defaultMessage: 'This field is required',
  },
  weaviateErrorPortRange: {
    id: 'src.components.PropertiesPanel.CustomPanels.VectorDB.weaviateErrorPortRange',
    defaultMessage: 'Enter a port from 1 to 65535',
  },
  weaviateErrorVaultIncomplete: {
    id: 'src.components.PropertiesPanel.CustomPanels.VectorDB.weaviateErrorVaultIncomplete',
    defaultMessage: 'Enter a Vault provider and path after vault://',
  },
  weaviateErrorTlsRequired: {
    id: 'src.components.PropertiesPanel.CustomPanels.VectorDB.weaviateErrorTlsRequired',
    defaultMessage: 'TLS must be on when authentication is configured',
  },
});

/** Localized message for each Weaviate field validation code. */
export const weaviateErrorMessages: Record<WeaviateFieldError, MessageDescriptor> = {
  required: messages.weaviateErrorRequired,
  port_range: messages.weaviateErrorPortRange,
  vault_reference_incomplete: messages.weaviateErrorVaultIncomplete,
  tls_required: messages.weaviateErrorTlsRequired,
};
