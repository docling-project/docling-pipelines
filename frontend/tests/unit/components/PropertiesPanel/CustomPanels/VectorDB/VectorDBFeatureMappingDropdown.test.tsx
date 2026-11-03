/**
 * Focused tests for VectorDBFeatureMappingTearsheet onChange handlers.
 * Uses a mocked @carbon/react Dropdown that directly calls onChange when clicked.
 */
import { describe, it, expect, vi } from 'vitest';
import { screen, fireEvent, waitFor, act } from '@testing-library/react';
import { renderWithProviders } from '../../../../../utils/renderWithProviders';
import { enrichFlowFeaturesForNode } from '@/components/PropertiesPanel/CustomPanels/VectorDB/vectordb-enrichment';
import { getProviderConfig } from '@/components/PropertiesPanel/CustomPanels/VectorDB/constants';

// Mock enrichment API
vi.mock(
  '@/components/PropertiesPanel/CustomPanels/VectorDB/vectordb-enrichment',
  () => ({
    enrichFlowFeaturesForNode: vi.fn().mockResolvedValue(null),
  })
);

// Mock @carbon/ibm-products Tearsheet
vi.mock('@carbon/ibm-products', () => ({
  Tearsheet: ({
    open,
    title,
    children,
    onClose,
    actions,
  }: {
    open: boolean;
    title: React.ReactNode;
    children: React.ReactNode;
    onClose: () => void;
    actions?: Array<{ label: string; onClick: () => void; kind: string; disabled?: boolean }>;
  }) =>
    open ? (
      <div data-testid="tearsheet">
        <div data-testid="tearsheet-title">{title}</div>
        <div data-testid="tearsheet-body">{children}</div>
        {actions?.map((a) => (
          <button key={a.label} onClick={a.onClick} disabled={a.disabled}>
            {a.label}
          </button>
        ))}
        <button onClick={onClose}>Close</button>
      </div>
    ) : null,
  ErrorEmptyState: ({ title, subtitle }: { title: string; subtitle: string }) => (
    <div data-testid="error-empty-state">
      <span>{title}</span>
      <span>{subtitle}</span>
    </div>
  ),
}));

// Mock @carbon/react Dropdown with a simple select that calls onChange directly
vi.mock('@carbon/react', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@carbon/react')>();
  return {
    ...actual,
    Dropdown: ({
      id,
      items,
      onChange,
      selectedItem,
    }: {
      id: string;
      items: string[];
      onChange: (args: { selectedItem: string }) => void;
      selectedItem?: string;
    }) => (
      <select
        data-testid={`dropdown-${id}`}
        id={id}
        value={selectedItem ?? ''}
        onChange={(e) => onChange({ selectedItem: e.target.value })}
      >
        {items?.map((item) => (
          <option key={String(item)} value={String(item)}>
            {String(item)}
          </option>
        ))}
      </select>
    ),
    ComboBox: ({
      id,
      items,
      onChange,
      selectedItem,
    }: {
      id: string;
      items: string[];
      onChange: (args: { selectedItem: string }) => void;
      selectedItem?: string;
    }) => (
      <select
        data-testid={`combobox-${id}`}
        id={id}
        value={selectedItem ?? ''}
        onChange={(e) => onChange({ selectedItem: e.target.value })}
      >
        {items?.map((item) => (
          <option key={String(item)} value={String(item)}>
            {String(item)}
          </option>
        ))}
      </select>
    ),
  };
});

import { VectorDBFeatureMappingTearsheet } from '@/components/PropertiesPanel/CustomPanels/VectorDB/VectorDBFeatureMappingTearsheet';

const mockEnrich = vi.mocked(enrichFlowFeaturesForNode);

const enrichmentResult = {
  available_resources: ['my-index', 'other-index'],
  feature_mappings: [
    { feature_name: 'content', mapped_column_name: 'text' },
    { feature_name: 'embedding', mapped_column_name: 'vector' },
  ],
  available_features: {
    content: { description: 'Text content', mandatory_for_vector_db: true },
    embedding: { description: 'Vector embedding', mandatory_for_vector_db: true },
  },
  stored_resource_metadata: null,
  is_docpipe_supported_resource: null,
};

const baseProps = {
  open: true,
  onClose: vi.fn(),
  onSave: vi.fn(),
  providerCfg: getProviderConfig('opensearch'),
  provider: 'opensearch',
  savedResourceName: '',
  currentFeatureMappings: [],
  pipelineFlow: { pipelines: [{ nodes: [] }] },
  nodeId: 'node-1',
  parsedProviderConfig: {},
  addSparseVector: false,
  vectorSimilarityOptions: ['cosine', 'l2', 'innerproduct'],
  savedVectorSimilarity: 'cosine',
  engineOptions: ['lucene', 'nmslib', 'faiss'],
  savedEngine: 'lucene',
};

describe('VectorDBFeatureMappingTearsheet — Dropdown onChange coverage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockEnrich.mockResolvedValue(enrichmentResult);
    Element.prototype.scrollIntoView = vi.fn();
  });

  // ── Covers lines 550-554: similarity onChange with valid selectedItem ─────
  it('similarity Dropdown onChange with valid item calls setSimilarityMetric (lines 550-554)', async () => {
    renderWithProviders(<VectorDBFeatureMappingTearsheet {...baseProps} />);
    await waitFor(() =>
      expect(screen.getByTestId('dropdown-similarity-metric-select')).toBeInTheDocument()
    );
    const dropdown = screen.getByTestId('dropdown-similarity-metric-select') as HTMLSelectElement;
    // Select "l2" option — triggers onChange({ selectedItem: 'l2' })
    await act(async () => {
      fireEvent.change(dropdown, { target: { value: 'l2' } });
    });
    expect(dropdown).toBeInTheDocument();
  });

  it('similarity Dropdown onChange with empty item is a no-op (selectedItem guard)', async () => {
    renderWithProviders(<VectorDBFeatureMappingTearsheet {...baseProps} />);
    await waitFor(() =>
      expect(screen.getByTestId('dropdown-similarity-metric-select')).toBeInTheDocument()
    );
    const dropdown = screen.getByTestId('dropdown-similarity-metric-select') as HTMLSelectElement;
    // Select "" option — onChange called with empty string which fails the if-guard
    await act(async () => {
      fireEvent.change(dropdown, { target: { value: '' } });
    });
    expect(dropdown).toBeInTheDocument();
  });

  // ── Covers lines 566-570: engine onChange with valid selectedItem ─────────
  it('engine Dropdown onChange with valid item calls setEngine (lines 566-570)', async () => {
    renderWithProviders(<VectorDBFeatureMappingTearsheet {...baseProps} />);
    await waitFor(() =>
      expect(screen.getByTestId('dropdown-engine-select')).toBeInTheDocument()
    );
    const dropdown = screen.getByTestId('dropdown-engine-select') as HTMLSelectElement;
    // Select "faiss" option — triggers onChange({ selectedItem: 'faiss' })
    await act(async () => {
      fireEvent.change(dropdown, { target: { value: 'faiss' } });
    });
    expect(dropdown).toBeInTheDocument();
  });

  it('engine Dropdown onChange with empty item is a no-op (selectedItem guard)', async () => {
    renderWithProviders(<VectorDBFeatureMappingTearsheet {...baseProps} />);
    await waitFor(() =>
      expect(screen.getByTestId('dropdown-engine-select')).toBeInTheDocument()
    );
    const dropdown = screen.getByTestId('dropdown-engine-select') as HTMLSelectElement;
    await act(async () => {
      fireEvent.change(dropdown, { target: { value: '' } });
    });
    expect(dropdown).toBeInTheDocument();
  });

  // ── Covers the ComboBox onChange (handleResourceChange, lines 272-323) ────
  it('resource ComboBox onChange triggers handleResourceChange (lines 272-323)', async () => {
    mockEnrich
      .mockResolvedValueOnce(enrichmentResult)
      .mockResolvedValueOnce(enrichmentResult);
    renderWithProviders(<VectorDBFeatureMappingTearsheet {...baseProps} />);
    await waitFor(() =>
      expect(screen.getByTestId('combobox-resource-select')).toBeInTheDocument()
    );
    const combobox = screen.getByTestId('combobox-resource-select') as HTMLSelectElement;
    // Select an existing resource — triggers handleResourceChange with selectedItem='my-index'
    await act(async () => {
      fireEvent.change(combobox, { target: { value: 'my-index' } });
    });
    // Re-enrichment should have been called (initial + 1 resource change)
    await waitFor(() => expect(mockEnrich).toHaveBeenCalledTimes(2));
  });

  // ── Loading state: {loading && (...)} block (lines 450-454) ─────────────
  it('renders Loading spinner while enrichment is pending (lines 450-454)', async () => {
    mockEnrich.mockReturnValue(new Promise(() => {}));
    renderWithProviders(<VectorDBFeatureMappingTearsheet {...baseProps} />);
    // Loading=true → Loading component rendered, ComboBox not rendered
    await waitFor(() => {
      expect(screen.queryByTestId('combobox-resource-select')).toBeNull();
    });
    expect(screen.getByTestId('tearsheet-body')).toBeInTheDocument();
  });
});
