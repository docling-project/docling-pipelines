import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, fireEvent } from '@testing-library/react';
import { renderWithProviders } from '../../../../../utils/renderWithProviders';
import { VectorDBPanelBody } from '@/components/PropertiesPanel/CustomPanels/VectorDB/VectorDB';

type TearsheetProps = Record<string, unknown> & {
  onSave: (data: Record<string, unknown>) => void;
};

// Capture the props the panel passes to the tearsheet so the metadata wiring can be asserted
// without opening the real tearsheet (which would call the enrichment API).
const tearsheetProps: { current: TearsheetProps | null } = { current: null };

vi.mock(
  '@/components/PropertiesPanel/CustomPanels/VectorDB/VectorDBFeatureMappingTearsheet',
  () => ({
    VectorDBFeatureMappingTearsheet: (props: TearsheetProps) => {
      tearsheetProps.current = props;
      return (
        <button
          data-testid="stub-save-new"
          onClick={() =>
            props.onSave({
              resourceName: 'res',
              similarityMetric: 'L2',
              engine: 'faiss',
              indexType: 'IVF_FLAT',
              clearIndexParameters: true,
              featureMappings: [],
              addSparseVector: false,
            })
          }
        >
          stub-save-new
        </button>
      );
    },
  })
);

const APPLICABILITY = {
  index_families: [
    { id: 'cpu_dense', index_types: ['FLAT', 'HNSW'], metric_types: ['L2'], feature_types: ['vector'] },
  ],
  lite: { index_types: ['FLAT'], default: 'FLAT' },
};

const makeController = (
  provider: string,
  providerConfig: Record<string, unknown>,
  providers: Record<string, unknown> | null
) => {
  const updatePropertyValue = vi.fn();
  const controller = {
    getAppData: vi.fn(() => ({
      operatorMetadata: providers
        ? { vectordb: { attributes: { provider_config: { providers } } } }
        : {},
      nodeId: 'node-1',
      pipelineFlow: { pipelines: [{ nodes: [] }] },
      nodeFeatureMap: {},
    })),
    getPropertyValue: vi.fn((p: { name: string }) => {
      if (p.name === 'provider') return provider;
      if (p.name === 'provider_config') return JSON.stringify(providerConfig);
      return undefined;
    }),
    updatePropertyValue,
    getPipelineFlow: vi.fn(() => ({ pipelines: [{ nodes: [] }] })),
  };
  return { controller, updatePropertyValue };
};

const lastProviderConfigWrite = (updatePropertyValue: ReturnType<typeof vi.fn>) => {
  const calls = updatePropertyValue.mock.calls.filter(
    ([target]) => (target as { name: string }).name === 'provider_config'
  );
  return calls.at(-1)?.[1] as Record<string, unknown>;
};

describe('VectorDBPanelBody index type wiring', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    tearsheetProps.current = null;
  });

  it('passes the Milvus index_type valid values, default and applicability from metadata', () => {
    const { controller } = makeController('milvus', {}, {
      milvus: {
        properties: { index_type: { valid_values: ['FLAT', 'HNSW'], default: 'HNSW' } },
        applicability: APPLICABILITY,
      },
    });
    renderWithProviders(<VectorDBPanelBody controller={controller} />);

    expect(tearsheetProps.current?.indexTypeValidValues).toEqual(['FLAT', 'HNSW']);
    expect(tearsheetProps.current?.indexTypeDefault).toBe('HNSW');
    expect(tearsheetProps.current?.applicability).toEqual(APPLICABILITY);
  });

  it('reads the OpenSearch algorithm values under the algorithm key', () => {
    const { controller } = makeController('opensearch', {}, {
      opensearch: {
        properties: { algorithm: { valid_values: ['hnsw', 'ivf'], default: 'hnsw' } },
        applicability: { engine_algorithms: { faiss: ['hnsw', 'ivf'] } },
      },
    });
    renderWithProviders(<VectorDBPanelBody controller={controller} />);

    expect(tearsheetProps.current?.indexTypeValidValues).toEqual(['hnsw', 'ivf']);
    expect(tearsheetProps.current?.indexTypeDefault).toBe('hnsw');
    expect(tearsheetProps.current?.applicability).toEqual({
      engine_algorithms: { faiss: ['hnsw', 'ivf'] },
    });
  });

  it('passes undefined metadata props when the backend sends none, so the tearsheet falls back', () => {
    const { controller } = makeController('milvus', {}, null);
    renderWithProviders(<VectorDBPanelBody controller={controller} />);

    expect(tearsheetProps.current?.indexTypeValidValues).toBeUndefined();
    expect(tearsheetProps.current?.indexTypeDefault).toBeUndefined();
    expect(tearsheetProps.current?.applicability).toBeUndefined();
  });

  it('does not show index_type in the Advanced JSON textarea', () => {
    const { controller } = makeController('milvus', { index_type: 'IVF_FLAT', custom_opt: 'x' }, null);
    renderWithProviders(<VectorDBPanelBody controller={controller} />);

    const textarea = document.getElementById('vectordb-provider-config-textarea') as HTMLTextAreaElement;
    expect(textarea.value).toContain('custom_opt');
    expect(textarea.value).not.toContain('index_type');
  });

  it('does not show algorithm in the Advanced JSON textarea', () => {
    const { controller } = makeController('opensearch', { algorithm: 'ivf', custom_opt: 'x' }, null);
    renderWithProviders(<VectorDBPanelBody controller={controller} />);

    const textarea = document.getElementById('vectordb-provider-config-textarea') as HTMLTextAreaElement;
    expect(textarea.value).toContain('custom_opt');
    expect(textarea.value).not.toContain('algorithm');
  });

  it('keeps an existing index_type in provider_config when the Advanced JSON is edited', () => {
    const { controller, updatePropertyValue } = makeController(
      'milvus', { index_type: 'IVF_FLAT', custom_opt: 'x' }, null
    );
    renderWithProviders(<VectorDBPanelBody controller={controller} />);

    const textarea = document.getElementById('vectordb-provider-config-textarea') as HTMLTextAreaElement;
    fireEvent.change(textarea, { target: { value: '{"custom_opt": "y"}' } });

    const written = lastProviderConfigWrite(updatePropertyValue);
    expect(written.index_type).toBe('IVF_FLAT');
    expect(written.custom_opt).toBe('y');
  });

  it('saves the tearsheet index type under index_type for Milvus and keeps unrelated keys', () => {
    const { controller, updatePropertyValue } = makeController(
      'milvus', { custom_opt: 'x', index_parameters: { nlist: 128 } }, null
    );
    renderWithProviders(<VectorDBPanelBody controller={controller} />);
    // Stub payload sets clearIndexParameters: true.
    fireEvent.click(screen.getByTestId('stub-save-new'));

    const written = lastProviderConfigWrite(updatePropertyValue);
    expect(written.index_type).toBe('IVF_FLAT');
    expect(written.custom_opt).toBe('x');
    expect(written).not.toHaveProperty('index_parameters');
  });

  it('saves the tearsheet index type under algorithm for OpenSearch', () => {
    const { controller, updatePropertyValue } = makeController('opensearch', {}, null);
    renderWithProviders(<VectorDBPanelBody controller={controller} />);
    fireEvent.click(screen.getByTestId('stub-save-new'));

    const written = lastProviderConfigWrite(updatePropertyValue);
    expect(written.algorithm).toBe('IVF_FLAT');
    expect(written).not.toHaveProperty('index_type');
  });
});
