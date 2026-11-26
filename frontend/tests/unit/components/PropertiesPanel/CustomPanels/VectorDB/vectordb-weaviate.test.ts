import { describe, it, expect } from 'vitest';
import {
  applyGrpcOverride,
  buildEnrichmentConfig,
  changedKeys,
  firstInvalidField,
  hasTlsError,
  switchAuthType,
  switchConnectionType,
  validateWeaviateConfig,
  visibleErrors,
} from '@/components/PropertiesPanel/CustomPanels/VectorDB/vectordb-weaviate';

describe('validateWeaviateConfig', () => {
  it('accepts an empty config because the backend supplies defaults', () => {
    expect(validateWeaviateConfig({})).toEqual({});
  });

  it('reports a blank host and out-of-range ports for an on-prem connection', () => {
    expect(validateWeaviateConfig({ host: '  ' }).host).toBe('required');
    expect(validateWeaviateConfig({ port: 0 }).port).toBe('port_range');
    expect(validateWeaviateConfig({ port: 65536 }).port).toBe('port_range');
    expect(validateWeaviateConfig({ port: 'abc' }).port).toBe('port_range');
    expect(validateWeaviateConfig({ port: '' }).port).toBe('required');
    expect(validateWeaviateConfig({ grpc_port: 70000 }).grpc_port).toBe('port_range');
    expect(validateWeaviateConfig({ port: 1, grpc_port: 65535 })).toEqual({});
  });

  it('requires a cluster URL for a cloud connection and ignores on-prem keys', () => {
    expect(validateWeaviateConfig({ connection_type: 'cloud' }).cluster_url).toBe('required');
    expect(
      validateWeaviateConfig({ connection_type: 'cloud', cluster_url: 'https://x.weaviate.cloud', port: 0 })
    ).toEqual({});
  });

  it.each([
    ['api_key', { auth_type: 'api_key' }, ['api_key']],
    ['bearer_token', { auth_type: 'bearer_token' }, ['bearer_token']],
    ['client_password', { auth_type: 'client_password' }, ['username', 'password']],
  ])('requires the credentials of %s', (_name, config, fields) => {
    const errors = validateWeaviateConfig({ ...config, secure: true });
    for (const field of fields) {
      expect(errors[field as keyof typeof errors]).toBe('required');
    }
  });

  it('treats any non-empty credential, including a complete vault reference, as present', () => {
    const base = { auth_type: 'api_key', secure: true };
    expect(validateWeaviateConfig({ ...base, api_key: 'literal' })).toEqual({});
    expect(validateWeaviateConfig({ ...base, api_key: '$WEAVIATE_API_KEY' })).toEqual({});
    expect(validateWeaviateConfig({ ...base, api_key: '${WEAVIATE_API_KEY}' })).toEqual({});
    expect(validateWeaviateConfig({ ...base, api_key: 'vault://hashicorp/docpipe/weaviate#key' })).toEqual({});
    expect(validateWeaviateConfig({ ...base, api_key: 'vault://x/y' })).toEqual({});
  });

  it.each([
    'vault://hashicorp/#api_key',
    'vault://hashicorp/a//b',
    'vault://hashicorp/a/./b',
    'vault://hashicorp/a/../b',
    'vault://hashicorp/path#',
    'vault://hashicorp/path#a#b',
    'vault://hashicorp/path#api_key ',
    'vault://hashicorp/path with spaces#api_key',
    'vault://hashicorp/ path',
    'vault://hashicorp/path\t#api_key',
    'vault://hashicorp/path\n',
  ])('flags the vault reference %s whose path or key fragment is incomplete', (value) => {
    const errors = validateWeaviateConfig({ auth_type: 'api_key', secure: true, api_key: value });
    expect(errors.api_key).toBe('vault_reference_incomplete');
  });

  it.each(['vault://hashicorp/path#api_key', 'vault://hashicorp/a/b/c'])('accepts the complete vault reference %s', (value) => {
    expect(validateWeaviateConfig({ auth_type: 'api_key', secure: true, api_key: value })).toEqual({});
  });

  it.each(['vault://', 'vault://x', 'vault://x/'])('flags the incomplete vault reference %s', (value) => {
    const errors = validateWeaviateConfig({ auth_type: 'api_key', secure: true, api_key: value });
    expect(errors.api_key).toBe('vault_reference_incomplete');
  });

  describe('credentials over plaintext', () => {
    const auth = { auth_type: 'api_key', api_key: 'k' };

    it('rejects HTTP plaintext', () => {
      const errors = validateWeaviateConfig({ ...auth, secure: false });
      expect(errors.secure).toBe('tls_required');
      expect(hasTlsError(errors)).toBe(true);
    });

    it('rejects unset TLS because the default is plaintext', () => {
      expect(validateWeaviateConfig(auth).secure).toBe('tls_required');
    });

    it('rejects an explicit gRPC plaintext override under HTTP TLS', () => {
      const errors = validateWeaviateConfig({ ...auth, secure: true, grpc_secure: false });
      expect(errors.secure).toBeUndefined();
      expect(errors.grpc_secure).toBe('tls_required');
    });

    it('accepts HTTP TLS with gRPC TLS unset (inherited)', () => {
      expect(validateWeaviateConfig({ ...auth, secure: true })).toEqual({});
    });

    it('accepts HTTP and gRPC TLS explicitly on', () => {
      expect(validateWeaviateConfig({ ...auth, secure: true, grpc_secure: true })).toEqual({});
    });

    it('accepts plaintext without authentication', () => {
      expect(validateWeaviateConfig({ secure: false, grpc_secure: false })).toEqual({});
    });

    it('does not apply the rule to a cloud connection', () => {
      expect(
        validateWeaviateConfig({ ...auth, connection_type: 'cloud', cluster_url: 'https://x.weaviate.cloud' })
      ).toEqual({});
    });
  });
});

describe('firstInvalidField', () => {
  it('returns null for a valid config', () => {
    expect(firstInvalidField({})).toBeNull();
  });

  it('returns the first field in visual order', () => {
    expect(firstInvalidField({ password: 'required', port: 'port_range' })).toBe('port');
    expect(firstInvalidField({ api_key: 'required', secure: 'tls_required' })).toBe('secure');
  });
});

describe('switchConnectionType', () => {
  const onPrem = {
    connection_type: 'on-prem',
    host: 'h',
    port: 8080,
    secure: true,
    grpc_host: 'g',
    grpc_port: 50051,
    grpc_secure: true,
    auth_type: 'api_key',
    api_key: 'k',
    collection_name: 'Docs',
    custom_key: 1,
  };

  it('removes on-prem keys when switching to cloud and keeps unrelated keys', () => {
    expect(switchConnectionType(onPrem, 'cloud')).toEqual({
      connection_type: 'cloud',
      auth_type: 'api_key',
      api_key: 'k',
      collection_name: 'Docs',
      custom_key: 1,
    });
  });

  it('removes the cluster URL when switching to on-prem', () => {
    expect(
      switchConnectionType({ connection_type: 'cloud', cluster_url: 'https://x', custom_key: 1 }, 'on-prem')
    ).toEqual({ connection_type: 'on-prem', custom_key: 1 });
  });

  it('does not mutate its input', () => {
    const input = { ...onPrem };
    switchConnectionType(input, 'cloud');
    expect(input).toEqual(onPrem);
  });
});

describe('switchAuthType', () => {
  const config = {
    auth_type: 'client_password',
    username: 'u',
    password: 'p',
    api_key: 'a',
    bearer_token: 'b',
    host: 'h',
    custom_key: 1,
  };

  it.each(['none', 'api_key', 'bearer_token', 'client_password'] as const)(
    'removes every credential and writes auth_type %s together',
    (type) => {
      expect(switchAuthType(config, type)).toEqual({ auth_type: type, host: 'h', custom_key: 1 });
    }
  );
});

describe('applyGrpcOverride', () => {
  it('deletes grpc_host when set to empty so the backend inherits the HTTP host', () => {
    expect(applyGrpcOverride({ host: 'h', grpc_host: 'g' }, 'grpc_host', '')).toEqual({ host: 'h' });
    expect(applyGrpcOverride({ grpc_host: 'g' }, 'grpc_host', '   ')).toEqual({});
  });

  it('writes an explicit gRPC host', () => {
    expect(applyGrpcOverride({}, 'grpc_host', 'g')).toEqual({ grpc_host: 'g' });
  });

  it('deletes grpc_secure for "Same as HTTP" and writes explicit values, including false', () => {
    expect(applyGrpcOverride({ grpc_secure: true }, 'grpc_secure', null)).toEqual({});
    expect(applyGrpcOverride({}, 'grpc_secure', false)).toEqual({ grpc_secure: false });
    expect(applyGrpcOverride({}, 'grpc_secure', true)).toEqual({ grpc_secure: true });
  });
});

describe('buildEnrichmentConfig', () => {
  it('merges displayed on-prem defaults under saved values', () => {
    expect(buildEnrichmentConfig({})).toEqual({
      connection_type: 'on-prem',
      host: 'localhost',
      port: 8080,
      secure: false,
    });
    expect(buildEnrichmentConfig({ host: 'h', secure: true, collection_name: 'Docs' })).toEqual({
      connection_type: 'on-prem',
      host: 'h',
      port: 8080,
      secure: true,
      collection_name: 'Docs',
    });
  });

  it('adds no on-prem defaults for a cloud connection', () => {
    expect(buildEnrichmentConfig({ connection_type: 'cloud', cluster_url: 'https://x' })).toEqual({
      connection_type: 'cloud',
      cluster_url: 'https://x',
    });
  });

  it('keeps inherited gRPC values unset and preserves explicit ones', () => {
    const inherited = buildEnrichmentConfig({ grpc_host: '' });
    expect(inherited).not.toHaveProperty('grpc_host');
    expect(inherited).not.toHaveProperty('grpc_secure');

    const explicit = buildEnrichmentConfig({ grpc_host: 'g', grpc_secure: false });
    expect(explicit.grpc_host).toBe('g');
    expect(explicit.grpc_secure).toBe(false);
  });

  it('preserves unrelated keys', () => {
    expect(buildEnrichmentConfig({ timeout_init: 5 }).timeout_init).toBe(5);
  });
});

describe('changedKeys', () => {
  it('reports added, removed and changed keys', () => {
    expect(changedKeys({ a: 1, b: 2, c: 3 }, { a: 1, b: 5, d: 4 }).sort()).toEqual(['b', 'c', 'd']);
  });

  it('reports nothing for equal configurations', () => {
    expect(changedKeys({ a: 1 }, { a: 1 })).toEqual([]);
  });
});

describe('visibleErrors', () => {
  const errors = { host: 'required', api_key: 'required', secure: 'tls_required' } as const;

  it('hides every error before the user edits anything', () => {
    expect(visibleErrors(errors, new Set(), false)).toEqual({});
  });

  it('shows only the errors of edited fields', () => {
    expect(visibleErrors(errors, new Set(['host']), false)).toEqual({ host: 'required' });
  });

  it('shows the TLS error once the authentication method was changed', () => {
    expect(visibleErrors(errors, new Set(['auth_type']), false)).toEqual({ secure: 'tls_required' });
  });

  it('shows every error after a blocked open attempt', () => {
    expect(visibleErrors(errors, new Set(), true)).toEqual(errors);
  });
});
