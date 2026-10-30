import { defineMessages } from 'react-intl';

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
});
