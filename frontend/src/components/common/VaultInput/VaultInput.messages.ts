import { defineMessages } from 'react-intl';

export const messages = defineMessages({
  useVault: {
    id: 'src.components.common.VaultInput.useVault',
    defaultMessage: 'Use Vault',
  },
  vaultAriaLabel: {
    id: 'src.components.common.VaultInput.vaultAriaLabel',
    defaultMessage: 'Use Vault',
  },
  invalidVaultUri: {
    id: 'src.components.common.VaultInput.invalidVaultUri',
    defaultMessage: 'Enter the vault path, e.g. hashicorp/docpipe/opensearch#password',
  },
  helperText: {
    id: 'src.components.common.VaultInput.helperText',
    defaultMessage: 'Format: <provider>/<mount_or_path>[#<secret_key>]',
  },
});
