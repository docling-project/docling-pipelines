import React, { useEffect, useState } from 'react';
import { DefinitionTooltip, PasswordInput, Tag, TextArea, TextInput, Toggle } from '@carbon/react';
import { useIntl } from 'react-intl';
import { isVaultReference } from '@/utils/vault';
import { messages } from './VaultInput.messages';
import styles from './VaultInput.module.scss';

const VAULT_PREFIX = 'vault://';

/** Strip vault:// prefix for display; return '' if value is exactly 'vault://' */
const toDisplayValue = (full: string): string => {
  if (!isVaultReference(full)) { return full; }
  return full.slice(VAULT_PREFIX.length);
};

/** Prepend vault:// to the user-typed suffix to produce the stored URI */
const toFullUri = (suffix: string): string => `${VAULT_PREFIX}${suffix}`;

export interface VaultInputProps {
  id: string;
  labelText: string;
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  defaultValue?: string;
  invalid?: boolean;
  invalidText?: React.ReactNode;
  disabled?: boolean;
  helperText?: string;
  hideLabel?: boolean;
  multiline?: boolean;
  rows?: number;
  labelComponent?: React.ReactNode;
}

export function VaultInput({
  id,
  labelText,
  value = '',
  onChange,
  placeholder,
  defaultValue = '',
  invalid = false,
  invalidText,
  disabled,
  helperText,
  hideLabel = false,
  multiline = false,
  rows = 4,
  labelComponent,
}: VaultInputProps): React.JSX.Element {
  const intl = useIntl();
  const [useVault, setUseVault] = useState<boolean>(() => isVaultReference(value));

  // Last known direct (non-vault) value — restored when user toggles vault off
  const [lastDirectValue, setLastDirectValue] = useState<string>(() =>
    !isVaultReference(value) && value !== '' ? value : defaultValue
  );

  // Last known full vault URI — restored when user toggles vault on again.
  // Always stored with vault:// prefix; never shown directly.
  const [lastVaultValue, setLastVaultValue] = useState<string>(() =>
    isVaultReference(value) ? value : VAULT_PREFIX
  );

  // Sync toggle state when the external value prop changes (e.g. panel re-opens
  // with a different node selected, or the parent resets the field).
  useEffect(() => {
    if (isVaultReference(value)) {
      setUseVault(true);
      setLastVaultValue(value);
    } else if (value !== '') {
      setUseVault(false);
      setLastDirectValue(value);
    }
  }, [value]);

  const handleToggle = (checked: boolean): void => {
    setUseVault(checked);
    if (checked) {
      // Switching to vault mode — save the current direct value, restore last vault URI
      if (!isVaultReference(value) && value !== '') {
        setLastDirectValue(value);
      }
      onChange(lastVaultValue || VAULT_PREFIX);
    } else {
      // Switching to direct mode — save the current vault URI, restore last direct value
      if (isVaultReference(value)) {
        setLastVaultValue(value);
      }
      onChange(lastDirectValue || defaultValue || '');
    }
  };

  // The display suffix is what the user sees and types (no vault:// prefix).
  const displaySuffix = isVaultReference(value) ? toDisplayValue(value) : '';

  // Invalid when vault mode is on and the suffix is empty — vault:// alone
  // is not a resolvable reference.
  const isInvalidVaultUri = useVault && displaySuffix === '';
  const isInvalid = invalid || isInvalidVaultUri;

  const handleVaultChange = (e: React.ChangeEvent<HTMLInputElement>): void => {
    const suffix = e.target.value;
    // Always prepend vault:// so the stored value is always a valid URI prefix.
    // An empty suffix produces 'vault://' which is flagged as invalid above.
    onChange(toFullUri(suffix));
  };

  const renderDirectInput = (): React.JSX.Element => {
    if (multiline) {
      return (
        <TextArea
          id={id}
          labelText={labelText}
          hideLabel
          value={value}
          rows={rows}
          placeholder={placeholder}
          disabled={disabled}
          invalid={invalid}
          invalidText={invalidText}
          onChange={(e: React.ChangeEvent<HTMLTextAreaElement>) => {
            onChange(e.target.value);
          }}
          helperText={helperText}
        />
      );
    }

    return (
      <PasswordInput
        id={id}
        labelText={labelText}
        hideLabel
        value={value}
        placeholder={placeholder}
        disabled={disabled}
        invalid={invalid}
        invalidText={invalidText}
        onChange={(e: React.ChangeEvent<HTMLInputElement>) => {
          onChange(e.target.value);
        }}
        helperText={helperText}
      />
    );
  };

  return (
    <div className={styles.container}>
      <div className={styles.headerRow}>
        <div className={styles.labelSection}>
          {labelComponent ?? (!hideLabel ? <span className={styles.label}>{labelText}</span> : null)}
        </div>
        <div className={styles.toggleWrapper}>
          <DefinitionTooltip
            definition={
              <>
                Reference a secret stored in Vault instead of entering a plaintext value.
                <br /><br />
                Enter the path after <code>vault://</code>:
                <br />
                <code>&lt;provider&gt;/&lt;path&gt;#&lt;key&gt;</code>
                <br /><br />
                Example: <code>hashicorp/docpipe/opensearch#password</code>
                <br /><br />
                The provider name matches <code>DOCPIPE_VAULT_PROVIDER_NAME</code> (default: <code>hashicorp</code>).
                The path and key are determined by how your admin stored the secret in Vault.
              </>
            }
            openOnHover
            align="bottom-right"
          >
            {intl.formatMessage(messages.useVault)}
          </DefinitionTooltip>
          <Toggle
            id={`${id}-vault-toggle`}
            size="sm"
            aria-label={intl.formatMessage(messages.vaultAriaLabel)}
            labelA=""
            labelB=""
            toggled={useVault}
            disabled={disabled}
            onToggle={handleToggle}
          />
        </div>
      </div>

      {useVault ? (
        <div className={styles.vaultRefRow}>
          <Tag type="purple" size="sm" className={styles.vaultTag}>
            vault://
          </Tag>
          <TextInput
            id={id}
            labelText={labelText}
            hideLabel
            value={displaySuffix}
            disabled={disabled}
            invalid={isInvalid}
            invalidText={
              isInvalidVaultUri
                ? intl.formatMessage(messages.invalidVaultUri)
                : invalidText
            }
            onChange={handleVaultChange}
            placeholder={placeholder ?? 'provider/path#key'}
            helperText={helperText ?? intl.formatMessage(messages.helperText)}
          />
        </div>
      ) : (
        renderDirectInput()
      )}
    </div>
  );
}
