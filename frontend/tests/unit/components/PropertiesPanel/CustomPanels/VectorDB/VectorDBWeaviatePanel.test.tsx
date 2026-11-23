import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, fireEvent, waitFor } from '@testing-library/react';
import { renderWithProviders } from '../../../../../utils/renderWithProviders';
import { VectorDBPanelBody } from '@/components/PropertiesPanel/CustomPanels/VectorDB/VectorDB';
import { enrichFlowFeaturesForNode } from '@/components/PropertiesPanel/CustomPanels/VectorDB/vectordb-enrichment';

vi.mock(
  '@/components/PropertiesPanel/CustomPanels/VectorDB/vectordb-enrichment',
  () => ({ enrichFlowFeaturesForNode: vi.fn().mockResolvedValue(null) })
);

// The tearsheet is replaced by a marker so "opened" is observable without Carbon's portal.
vi.mock('@/components/PropertiesPanel/CustomPanels/VectorDB/VectorDBFeatureMappingTearsheet', () => ({
  VectorDBFeatureMappingTearsheet: ({
    open,
    parsedProviderConfig,
  }: {
    open: boolean;
    parsedProviderConfig: Record<string, unknown>;
  }) =>
    open ? <div data-testid="tearsheet">{JSON.stringify(parsedProviderConfig)}</div> : null,
}));

const PROVIDERS_METADATA = {
  vectordb: {
    attributes: {
      provider: { default: 'opensearch' },
      provider_config: {
        providers: {
          opensearch: { properties: {} },
          milvus: { properties: {} },
          weaviate: { properties: {} },
        },
      },
    },
  },
};

interface PanelState {
  provider?: string;
  providerConfig?: Record<string, unknown> | string;
  featureMappings?: unknown[];
  addSparseVector?: boolean;
  operatorMetadata?: Record<string, unknown>;
}

const makeController = ({
  provider = 'weaviate',
  providerConfig = {},
  featureMappings = [],
  addSparseVector,
  operatorMetadata = PROVIDERS_METADATA,
}: PanelState = {}) => ({
  getAppData: vi.fn(() => ({
    operatorMetadata,
    nodeId: 'node-1',
    pipelineFlow: { pipelines: [{ nodes: [] }] },
    nodeFeatureMap: {},
  })),
  getPropertyValue: vi.fn((p: { name: string }) => {
    if (p.name === 'provider') return provider;
    if (p.name === 'provider_config') return providerConfig;
    if (p.name === 'feature_mappings') return featureMappings;
    if (p.name === 'add_sparse_vector') return addSparseVector;
    return undefined;
  }),
  updatePropertyValue: vi.fn(),
  getPipelineFlow: vi.fn(() => ({ pipelines: [{ nodes: [] }] })),
});

const configWrites = (controller: ReturnType<typeof makeController>): Array<Record<string, unknown>> =>
  controller.updatePropertyValue.mock.calls
    .filter(([target]) => (target as { name: string }).name === 'provider_config')
    .map(([, value]) => value as Record<string, unknown>);

const clickAddFeatureMappings = (): void => {
  fireEvent.click(screen.getByRole('button', { name: /add feature mappings/i }));
};

const selectOption = (dropdownName: RegExp, optionName: string): void => {
  fireEvent.click(screen.getByRole('combobox', { name: dropdownName }));
  fireEvent.click(screen.getByRole('option', { name: optionName }));
};

describe('VectorDBPanelBody provider selection', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    Element.prototype.scrollIntoView = vi.fn();
  });

  it('lists the providers declared in operator metadata', () => {
    renderWithProviders(<VectorDBPanelBody controller={makeController()} />);

    fireEvent.click(screen.getByRole('combobox', { name: /^provider$/i }));

    expect(screen.getAllByRole('option').map((o) => o.textContent)).toEqual([
      'opensearch',
      'milvus',
      'weaviate',
    ]);
  });

  it('switching to Weaviate clears the previous provider configuration and mappings', () => {
    const controller = makeController({
      provider: 'milvus',
      providerConfig: { host: 'h', collection_name: 'c' },
      featureMappings: [{ feature_name: 'content', mapped_column_name: 'text' }],
    });
    renderWithProviders(<VectorDBPanelBody controller={controller} />);

    selectOption(/^provider$/i, 'weaviate');

    expect(controller.updatePropertyValue).toHaveBeenCalledWith({ name: 'provider' }, 'weaviate');
    expect(controller.updatePropertyValue).toHaveBeenCalledWith({ name: 'provider_config' }, {});
    expect(controller.updatePropertyValue).toHaveBeenCalledWith({ name: 'feature_mappings' }, []);
  });

  it('renders Weaviate controls, not another provider\'s, for the weaviate provider', () => {
    renderWithProviders(<VectorDBPanelBody controller={makeController()} />);

    expect(screen.getByRole('combobox', { name: /connection type/i })).toBeInTheDocument();
    expect(document.getElementById('weaviate-host')).toBeInTheDocument();
    expect(screen.queryByLabelText(/use ssl/i)).toBeNull();
  });
});

describe('VectorDBPanelBody Weaviate configuration writes', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    Element.prototype.scrollIntoView = vi.fn();
  });

  it('switching to Weaviate Cloud writes the connection type and drops on-prem keys in one write', () => {
    const controller = makeController({
      providerConfig: { host: 'db', port: 8080, grpc_port: 50051, collection_name: 'Docs' },
    });
    renderWithProviders(<VectorDBPanelBody controller={controller} />);

    selectOption(/connection type/i, 'Weaviate Cloud');

    expect(configWrites(controller)).toEqual([{ connection_type: 'cloud', collection_name: 'Docs' }]);
  });

  it('switching the authentication method replaces credentials and keeps unrelated keys in one write', () => {
    const controller = makeController({
      providerConfig: { host: 'db', secure: true, auth_type: 'api_key', api_key: 'k' },
    });
    renderWithProviders(<VectorDBPanelBody controller={controller} />);

    selectOption(/authentication method/i, 'Username and password');

    expect(configWrites(controller)).toEqual([
      { host: 'db', secure: true, auth_type: 'client_password' },
    ]);
  });

  it('stores an explicit gRPC TLS choice and removes it again for "Same as HTTP"', () => {
    const controller = makeController({ providerConfig: { host: 'db', grpc_secure: false } });
    renderWithProviders(<VectorDBPanelBody controller={controller} />);

    selectOption(/grpc tls/i, 'Same as HTTP');

    expect(configWrites(controller)).toEqual([{ host: 'db' }]);
  });

  it('keeps an unset gRPC host out of the saved configuration', () => {
    const controller = makeController({ providerConfig: { host: 'db', grpc_host: 'g' } });
    renderWithProviders(<VectorDBPanelBody controller={controller} />);

    fireEvent.change(document.getElementById('weaviate-grpc-host') as HTMLElement, { target: { value: '' } });

    expect(configWrites(controller)).toEqual([{ host: 'db' }]);
  });
});

describe('VectorDBPanelBody Weaviate validation gating', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    Element.prototype.scrollIntoView = vi.fn();
  });

  it('opens the tearsheet for a valid configuration', () => {
    renderWithProviders(
      <VectorDBPanelBody controller={makeController({ providerConfig: { host: 'db', port: 8080 } })} />
    );

    clickAddFeatureMappings();

    expect(screen.getByTestId('tearsheet')).toBeInTheDocument();
  });

  it('blocks the open for a missing cluster URL, shows the error, and focuses the field', async () => {
    renderWithProviders(
      <VectorDBPanelBody controller={makeController({ providerConfig: { connection_type: 'cloud' } })} />
    );

    expect(screen.queryByText('This field is required')).toBeNull();
    clickAddFeatureMappings();

    expect(screen.queryByTestId('tearsheet')).toBeNull();
    expect(enrichFlowFeaturesForNode).not.toHaveBeenCalled();
    expect(screen.getByText('This field is required')).toBeInTheDocument();
    await waitFor(() => { expect(document.getElementById('weaviate-cluster-url')).toHaveFocus(); });
  });

  it('focuses the first invalid field in visual order', async () => {
    renderWithProviders(
      <VectorDBPanelBody
        controller={makeController({
          providerConfig: { host: 'db', port: 70000, auth_type: 'api_key', secure: true, api_key: '' },
        })}
      />
    );

    clickAddFeatureMappings();

    expect(screen.queryByTestId('tearsheet')).toBeNull();
    await waitFor(() => { expect(document.getElementById('weaviate-port')).toHaveFocus(); });
  });

  it('expands a collapsed Authentication section and focuses the invalid credential field', async () => {
    renderWithProviders(
      <VectorDBPanelBody
        controller={makeController({
          providerConfig: { host: 'db', secure: true, auth_type: 'api_key', api_key: '' },
        })}
      />
    );
    const authHeading = screen.getByRole('button', { name: /^authentication$/i });
    fireEvent.click(authHeading);
    expect(authHeading).toHaveAttribute('aria-expanded', 'false');

    clickAddFeatureMappings();

    expect(screen.queryByTestId('tearsheet')).toBeNull();
    await waitFor(() => { expect(authHeading).toHaveAttribute('aria-expanded', 'true'); });
    await waitFor(() => { expect(document.getElementById('weaviate-api-key')).toHaveFocus(); });
  });

  it('expands a collapsed Connection section and focuses the invalid connection field', async () => {
    renderWithProviders(
      <VectorDBPanelBody controller={makeController({ providerConfig: { connection_type: 'cloud' } })} />
    );
    const connectionHeading = screen.getByRole('button', { name: /^connection$/i });
    fireEvent.click(connectionHeading);
    expect(connectionHeading).toHaveAttribute('aria-expanded', 'false');

    clickAddFeatureMappings();

    await waitFor(() => { expect(connectionHeading).toHaveAttribute('aria-expanded', 'true'); });
    await waitFor(() => { expect(document.getElementById('weaviate-cluster-url')).toHaveFocus(); });
  });

  it('blocks the open when authentication is configured without TLS and explains why', () => {
    renderWithProviders(
      <VectorDBPanelBody
        controller={makeController({
          providerConfig: { host: 'db', auth_type: 'api_key', api_key: 'k' },
        })}
      />
    );

    clickAddFeatureMappings();

    expect(screen.queryByTestId('tearsheet')).toBeNull();
    expect(enrichFlowFeaturesForNode).not.toHaveBeenCalled();
    expect(screen.getAllByText(/both http and grpc must use tls/i).length).toBeGreaterThan(0);
  });

  it('blocks the open for a credential left as an empty Vault reference and marks the field invalid', async () => {
    renderWithProviders(
      <VectorDBPanelBody
        controller={makeController({
          providerConfig: { host: 'db', secure: true, auth_type: 'api_key', api_key: 'vault://' },
        })}
      />
    );

    clickAddFeatureMappings();

    expect(screen.queryByTestId('tearsheet')).toBeNull();
    expect(enrichFlowFeaturesForNode).not.toHaveBeenCalled();
    expect(document.getElementById('weaviate-api-key')).toHaveAttribute('aria-invalid', 'true');
    await waitFor(() => { expect(document.getElementById('weaviate-api-key')).toHaveFocus(); });
  });

  it('blocks the open for a Vault reference without a path and shows the field error', () => {
    renderWithProviders(
      <VectorDBPanelBody
        controller={makeController({
          providerConfig: { host: 'db', secure: true, auth_type: 'api_key', api_key: 'vault://hashicorp' },
        })}
      />
    );

    clickAddFeatureMappings();

    expect(screen.queryByTestId('tearsheet')).toBeNull();
    expect(screen.getByText('Enter a Vault provider and path after vault://')).toBeInTheDocument();
  });

  it('accepts a complete Vault reference as a present credential', () => {
    renderWithProviders(
      <VectorDBPanelBody
        controller={makeController({
          providerConfig: {
            host: 'db',
            secure: true,
            auth_type: 'api_key',
            api_key: 'vault://kv/weaviate/key',
          },
        })}
      />
    );

    clickAddFeatureMappings();

    expect(screen.getByTestId('tearsheet')).toBeInTheDocument();
  });

  it('shows no field errors before the user edits or attempts to open', () => {
    renderWithProviders(
      <VectorDBPanelBody controller={makeController({ providerConfig: { connection_type: 'cloud' } })} />
    );

    expect(screen.queryByText('This field is required')).toBeNull();
    expect(document.getElementById('weaviate-cluster-url')).not.toHaveAttribute('aria-invalid', 'true');
  });
});

describe('VectorDBPanelBody Weaviate Advanced JSON and enrichment payload', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    Element.prototype.scrollIntoView = vi.fn();
  });

  const savedConfig = {
    host: 'db',
    collection_name: 'Docs',
    distance_metric: 'cosine',
    index_type: 'hnsw',
    index_parameters: { ef: 64 },
    custom_option: 'x',
  };

  const advancedValue = (): Record<string, unknown> =>
    JSON.parse((document.getElementById('vectordb-provider-config-textarea') as HTMLTextAreaElement).value) as Record<string, unknown>;

  it('shows index_type, index_parameters and unrelated keys in Advanced JSON but not managed keys', () => {
    renderWithProviders(
      <VectorDBPanelBody controller={makeController({ providerConfig: savedConfig })} />
    );

    expect(advancedValue()).toEqual({
      index_type: 'hnsw',
      index_parameters: { ef: 64 },
      custom_option: 'x',
    });
  });

  it('keeps managed keys winning and preserves index_parameters when Advanced JSON is edited', () => {
    const controller = makeController({ providerConfig: savedConfig });
    renderWithProviders(<VectorDBPanelBody controller={controller} />);

    fireEvent.change(document.getElementById('vectordb-provider-config-textarea') as HTMLElement, {
      target: { value: JSON.stringify({ host: 'evil', index_parameters: { ef: 128 }, custom_option: 'y' }) },
    });

    expect(configWrites(controller)).toEqual([
      {
        host: 'db',
        collection_name: 'Docs',
        distance_metric: 'cosine',
        index_parameters: { ef: 128 },
        custom_option: 'y',
      },
    ]);
  });

  it('keeps index_parameters across a connection type switch', () => {
    const controller = makeController({ providerConfig: savedConfig });
    renderWithProviders(<VectorDBPanelBody controller={controller} />);

    selectOption(/connection type/i, 'Weaviate Cloud');

    expect(configWrites(controller)[0]).toMatchObject({
      connection_type: 'cloud',
      index_parameters: { ef: 64 },
    });
  });

  it('sends displayed defaults to enrichment and omits index settings and unset gRPC fields', () => {
    renderWithProviders(
      <VectorDBPanelBody
        controller={makeController({ providerConfig: { ...savedConfig, host: 'db' } })}
      />
    );

    clickAddFeatureMappings();

    const sent = JSON.parse(screen.getByTestId('tearsheet').textContent ?? '{}') as Record<string, unknown>;
    expect(sent).toMatchObject({ connection_type: 'on-prem', host: 'db', port: 8080, secure: false });
    expect(sent).not.toHaveProperty('index_type');
    expect(sent).not.toHaveProperty('index_parameters');
    expect(sent).not.toHaveProperty('grpc_host');
    expect(sent).not.toHaveProperty('grpc_secure');
  });
});

describe('VectorDBPanelBody OpenSearch and Milvus regressions', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    Element.prototype.scrollIntoView = vi.fn();
  });

  it('keeps algorithm visible in Advanced JSON for OpenSearch while index_name stays managed', () => {
    renderWithProviders(
      <VectorDBPanelBody
        controller={makeController({
          provider: 'opensearch',
          providerConfig: { host: 'h', index_name: 'idx', space_type: 'l2', engine: 'faiss', algorithm: 'hnsw' },
        })}
      />
    );

    const advanced = JSON.parse(
      (document.getElementById('vectordb-provider-config-textarea') as HTMLTextAreaElement).value
    ) as Record<string, unknown>;
    expect(advanced).toEqual({ algorithm: 'hnsw' });
  });

  it('keeps index_type visible in Advanced JSON for Milvus', () => {
    renderWithProviders(
      <VectorDBPanelBody
        controller={makeController({
          provider: 'milvus',
          providerConfig: { host: 'h', collection_name: 'c', metric_type: 'L2', index_type: 'HNSW' },
        })}
      />
    );

    const advanced = JSON.parse(
      (document.getElementById('vectordb-provider-config-textarea') as HTMLTextAreaElement).value
    ) as Record<string, unknown>;
    expect(advanced).toEqual({ index_type: 'HNSW' });
  });

  it('does not render Weaviate controls for OpenSearch or Milvus', () => {
    const { unmount } = renderWithProviders(
      <VectorDBPanelBody controller={makeController({ provider: 'opensearch' })} />
    );
    expect(document.getElementById('weaviate-host')).toBeNull();
    unmount();

    renderWithProviders(<VectorDBPanelBody controller={makeController({ provider: 'milvus' })} />);
    expect(document.getElementById('weaviate-host')).toBeNull();
  });

  it('does not gate the tearsheet on Weaviate validation for other providers', () => {
    renderWithProviders(
      <VectorDBPanelBody
        controller={makeController({ provider: 'opensearch', providerConfig: { host: 'h' } })}
      />
    );

    clickAddFeatureMappings();

    expect(screen.getByTestId('tearsheet')).toBeInTheDocument();
  });
});
