import { describe, it, expect } from 'vitest';
import { migrateLegacyCredentials } from '@/components/PropertiesPanel/CustomPanels/StorageOutput/legacyCredentials';

describe('migrateLegacyCredentials', () => {
  it.each([
    ['no credentials block', { provider: 's3', provider_config: { bucket: 'b' } }],
    ['empty credentials', { provider: 's3', provider_config: {}, credentials: {} }],
    ['string credentials (whole-object vault reference)', { provider: 's3', provider_config: {}, credentials: 'vault://hashicorp/x' }],
  ])('returns null when there is nothing to migrate: %s', (_label, config) => {
    expect(migrateLegacyCredentials(config)).toBeNull();
  });

  it('copies credentials into provider_config and removes the credentials key', () => {
    const result = migrateLegacyCredentials({
      provider: 's3',
      provider_config: { bucket: 'b' },
      credentials: { access_key: 'AK', secret_key: 'SK' }, // pragma: allowlist secret
    });

    expect(result).toEqual({
      provider: 's3',
      provider_config: { bucket: 'b', access_key: 'AK', secret_key: 'SK' }, // pragma: allowlist secret
    });
  });

  it('lets credentials win over provider_config when both have a real value', () => {
    const result = migrateLegacyCredentials({
      provider: 's3',
      provider_config: { access_key: 'from-provider-config' },
      credentials: { access_key: 'from-credentials' },
    });

    expect(result?.provider_config).toEqual({ access_key: 'from-credentials' });
  });

  it.each([null, undefined, '', '   '])(
    'does not let a blank credentials value (%j) override or add a provider_config value',
    (blank) => {
      const result = migrateLegacyCredentials({
        provider: 's3',
        provider_config: { access_key: 'keep-me' },
        credentials: { access_key: blank, secret_key: blank, bucket: 'b' },
      });

      expect(result?.provider_config).toEqual({ access_key: 'keep-me', bucket: 'b' });
    }
  );

  it('overrides null values seeded in provider_config', () => {
    const result = migrateLegacyCredentials({
      provider: 'google_drive',
      provider_config: { service_account_json_path: null },
      credentials: { service_account_json_path: '/sa.json' },
    });

    expect(result?.provider_config).toEqual({ service_account_json_path: '/sa.json' });
  });

  it('renames the legacy box credentials_json_path to credentials_path', () => {
    const result = migrateLegacyCredentials({
      provider: 'box',
      provider_config: { folder_id: '0' },
      credentials: { credentials_json_path: '/box.json' },
    });

    expect(result?.provider_config).toEqual({ folder_id: '0', credentials_path: '/box.json' });
  });
});
