import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, fireEvent, waitFor, act } from '@testing-library/react';
import { renderWithProviders } from '../../../../../utils/renderWithProviders';
import { VectorDBFeatureMappingTearsheet } from '@/components/PropertiesPanel/CustomPanels/VectorDB/VectorDBFeatureMappingTearsheet';
import { getProviderConfig } from '@/components/PropertiesPanel/CustomPanels/VectorDB/constants';
import { enrichFlowFeaturesForNode } from '@/components/PropertiesPanel/CustomPanels/VectorDB/vectordb-enrichment';
import type { VectorDBEnrichmentResult } from '@/types';

vi.mock(
  '@/components/PropertiesPanel/CustomPanels/VectorDB/vectordb-enrichment',
  () => ({ enrichFlowFeaturesForNode: vi.fn().mockResolvedValue(null) })
);

vi.mock('@carbon/ibm-products', () => ({
  Tearsheet: ({
    open,
    children,
    onClose,
    actions,
  }: {
    open: boolean;
    children: React.ReactNode;
    onClose: () => void;
    actions?: Array<{ label: string; onClick: () => void; disabled?: boolean }>;
  }) =>
    open ? (
      <div data-testid="tearsheet">
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

const mockEnrich = vi.mocked(enrichFlowFeaturesForNode);

const DISTANCE_METRICS = ['cosine', 'dot', 'l2-squared', 'manhattan', 'hamming'];

const baseProps = {
  open: true,
  onClose: vi.fn(),
  onSave: vi.fn(),
  providerCfg: getProviderConfig('weaviate'),
  provider: 'weaviate',
  savedResourceName: '',
  currentFeatureMappings: [],
  pipelineFlow: { pipelines: [{ nodes: [] }] },
  nodeId: 'node-1',
  parsedProviderConfig: { host: 'db' },
  addSparseVector: false,
  vectorSimilarityOptions: DISTANCE_METRICS,
  savedVectorSimilarity: 'cosine',
  engineOptions: [] as string[],
  savedEngine: '',
};

const feature = (name: string, mandatory = false) => ({
  name,
  type: 'string',
  description: name,
  available_for_filter: false,
  available_for_vector_db: true,
  mandatory_for_vector_db: mandatory,
  node_id: 'node-1',
  tags: [] as string[],
});

const result = (overrides: Partial<VectorDBEnrichmentResult> = {}): VectorDBEnrichmentResult => ({
  available_resources: ['Docs'],
  selected_resource_schema: {},
  feature_mappings: [{ feature_name: 'content', mapped_column_name: 'text' }],
  is_docpipe_supported_resource: { supported: true },
  stored_resource_metadata: { vector_similarity: null, dimension_size: null },
  available_features: { content: feature('content', true) },
  ...overrides,
});

const waitForControls = async (): Promise<void> => {
  await waitFor(() => { expect(document.getElementById('resource-select')).toBeInTheDocument(); });
};

describe('VectorDBFeatureMappingTearsheet - Weaviate collection naming', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockEnrich.mockResolvedValue(result());
    Element.prototype.scrollIntoView = vi.fn();
  });

  it('uses the Weaviate example as the new-name placeholder', async () => {
    renderWithProviders(<VectorDBFeatureMappingTearsheet {...baseProps} />);
    await waitForControls();

    expect(document.getElementById('new-resource-name')).toHaveAttribute('placeholder', 'e.g. DocumentChunks');
  });

  it.each(['DocumentChunks', 'Docs_2025', 'A'])('accepts the collection name %s', async (name) => {
    renderWithProviders(<VectorDBFeatureMappingTearsheet {...baseProps} />);
    await waitForControls();

    fireEvent.change(document.getElementById('new-resource-name') as HTMLElement, { target: { value: name } });

    expect(screen.getByRole('button', { name: /^save$/i })).not.toBeDisabled();
    expect(document.getElementById('new-resource-name')).not.toHaveAttribute('aria-invalid', 'true');
  });

  it.each(['documentChunks', '2Docs', 'Doc-Chunks', 'Doc Chunks'])(
    'rejects the collection name %s with the Weaviate naming message',
    async (name) => {
      renderWithProviders(<VectorDBFeatureMappingTearsheet {...baseProps} />);
      await waitForControls();

      fireEvent.change(document.getElementById('new-resource-name') as HTMLElement, { target: { value: name } });

      expect(screen.getByRole('button', { name: /^save$/i })).toBeDisabled();
      expect(screen.getByText(/must start with an uppercase letter/i)).toBeInTheDocument();
    }
  );

  it('requires a name when the field is empty', async () => {
    renderWithProviders(<VectorDBFeatureMappingTearsheet {...baseProps} />);
    await waitForControls();

    expect(screen.getByText('Name is required')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^save$/i })).toBeDisabled();
  });

  it('rejects a name that matches an existing collection', async () => {
    renderWithProviders(<VectorDBFeatureMappingTearsheet {...baseProps} />);
    await waitForControls();

    fireEvent.change(document.getElementById('new-resource-name') as HTMLElement, { target: { value: 'Docs' } });

    expect(screen.getByText(/already exists/i)).toBeInTheDocument();
  });

  it('keeps the generic rule for OpenSearch', async () => {
    renderWithProviders(
      <VectorDBFeatureMappingTearsheet
        {...baseProps}
        provider="opensearch"
        providerCfg={getProviderConfig('opensearch')}
        vectorSimilarityOptions={['cosine', 'l2']}
        engineOptions={['lucene']}
        savedEngine="lucene"
      />
    );
    await waitForControls();

    fireEvent.change(document.getElementById('new-resource-name') as HTMLElement, { target: { value: 'lower_ok' } });

    expect(screen.getByRole('button', { name: /^save$/i })).not.toBeDisabled();
  });
});

describe('VectorDBFeatureMappingTearsheet - Weaviate distance metric', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    Element.prototype.scrollIntoView = vi.fn();
  });

  it('offers the five distance metrics and no engine selector for a new collection', async () => {
    mockEnrich.mockResolvedValue(result());
    renderWithProviders(<VectorDBFeatureMappingTearsheet {...baseProps} />);
    await waitForControls();

    fireEvent.click(screen.getByRole('combobox', { name: /distance metric/i }));

    expect(screen.getAllByRole('option').map((o) => o.textContent)).toEqual([
      'Cosine similarity',
      'Dot product',
      'Squared Euclidean distance',
      'Manhattan distance',
      'Hamming distance',
    ]);
    expect(document.getElementById('engine-select')).toBeNull();
  });

  it('shows an engine selector for OpenSearch', async () => {
    mockEnrich.mockResolvedValue(result());
    renderWithProviders(
      <VectorDBFeatureMappingTearsheet
        {...baseProps}
        provider="opensearch"
        providerCfg={getProviderConfig('opensearch')}
        vectorSimilarityOptions={['cosine', 'l2']}
        engineOptions={['lucene']}
        savedEngine="lucene"
      />
    );
    await waitForControls();

    expect(document.getElementById('engine-select')).toBeInTheDocument();
  });

  it('shows the stored metric of an existing collection as read-only, including l2-squared', async () => {
    mockEnrich.mockResolvedValue(
      result({ stored_resource_metadata: { vector_similarity: 'l2-squared', dimension_size: 768 } })
    );
    renderWithProviders(<VectorDBFeatureMappingTearsheet {...baseProps} savedResourceName="Docs" />);

    await waitFor(() => {
      expect(document.getElementById('similarity-metric-readonly')).toHaveValue('Squared Euclidean distance');
    });
    expect(document.getElementById('similarity-metric-readonly')).toBeDisabled();
    expect(document.getElementById('dimension-size-readonly')).toHaveValue('768');
  });

  it('shows an unknown stored metric unlabeled', async () => {
    mockEnrich.mockResolvedValue(
      result({ stored_resource_metadata: { vector_similarity: 'custom-metric', dimension_size: null } })
    );
    renderWithProviders(<VectorDBFeatureMappingTearsheet {...baseProps} savedResourceName="Docs" />);

    await waitFor(() => {
      expect(document.getElementById('similarity-metric-readonly')).toHaveValue('custom-metric');
    });
  });
});

describe('VectorDBFeatureMappingTearsheet - BM25 option', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    Element.prototype.scrollIntoView = vi.fn();
  });

  const milvusProps = {
    ...baseProps,
    provider: 'milvus',
    providerCfg: getProviderConfig('milvus'),
    vectorSimilarityOptions: ['L2', 'IP', 'COSINE'],
    savedVectorSimilarity: 'L2',
  };

  it('shows the BM25 checkbox for Weaviate with sparse (BM25) wording', async () => {
    mockEnrich.mockResolvedValue(result());
    renderWithProviders(<VectorDBFeatureMappingTearsheet {...baseProps} />);
    await waitForControls();

    expect(
      screen.getByRole('checkbox', { name: 'Enable sparse (BM25) keyword retrieval' })
    ).toBeInTheDocument();
    expect(screen.queryByText(/compute sparse vectors for hybrid search/i)).toBeNull();
  });

  describe('BM25 tooltip on the option text', () => {
    const TIP = /without generating or storing separate sparse vectors/i;

    const setup = async (): Promise<HTMLElement> => {
      mockEnrich.mockResolvedValue(result());
      renderWithProviders(<VectorDBFeatureMappingTearsheet {...baseProps} />);
      await waitForControls();
      return screen.getByRole('checkbox', { name: /sparse \(bm25\) keyword retrieval/i });
    };

    // The pointer handlers live on the wrapper around the checkbox and its text.
    const hoverTarget = (checkbox: HTMLElement): HTMLElement => checkbox.parentElement as HTMLElement;

    it('does not show the tip immediately on hover', async () => {
      const checkbox = await setup();
      fireEvent.mouseEnter(hoverTarget(checkbox));
      expect(screen.queryByRole('tooltip')).toBeNull();
    });

    it('does not show the tip when the pointer only passes over the option', async () => {
      const checkbox = await setup();
      fireEvent.mouseEnter(hoverTarget(checkbox));
      fireEvent.mouseLeave(hoverTarget(checkbox));
      await new Promise((resolve) => setTimeout(resolve, 900));
      expect(screen.queryByRole('tooltip')).toBeNull();
    });

    it('shows the tip once the pointer rests on the option', async () => {
      const checkbox = await setup();
      fireEvent.mouseEnter(hoverTarget(checkbox));
      expect(await screen.findByRole('tooltip', undefined, { timeout: 2000 })).toHaveTextContent(TIP);
    });

    it('shows the tip at once on keyboard focus and closes it on Escape', async () => {
      const checkbox = await setup();
      act(() => { checkbox.focus(); });
      expect(await screen.findByRole('tooltip')).toHaveTextContent(TIP);
      fireEvent.keyDown(checkbox, { key: 'Escape' });
      await waitFor(() => { expect(screen.queryByRole('tooltip')).toBeNull(); });
    });

    it('exposes the same text as the checkbox description for assistive technology', async () => {
      const checkbox = await setup();
      expect(checkbox).toHaveAccessibleDescription(TIP);
    });

    it('still toggles the option when the checkbox is clicked', async () => {
      const checkbox = await setup();
      expect(checkbox).not.toBeChecked();
      fireEvent.click(checkbox);
      await waitFor(() => { expect(checkbox).toBeChecked(); });
    });
  });

  it('keeps the sparse-vector wording for Milvus and shows no tooltip', async () => {
    mockEnrich.mockResolvedValue(result());
    renderWithProviders(<VectorDBFeatureMappingTearsheet {...milvusProps} />);
    await waitForControls();

    expect(screen.getByRole('checkbox', { name: /sparse vectors for hybrid search/i })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /what is this/i })).toBeNull();
    expect(screen.queryByText(/without generating or storing separate sparse vectors/i)).toBeNull();
  });

  it('hides the checkbox for OpenSearch', async () => {
    mockEnrich.mockResolvedValue(result());
    renderWithProviders(
      <VectorDBFeatureMappingTearsheet
        {...baseProps}
        provider="opensearch"
        providerCfg={getProviderConfig('opensearch')}
        vectorSimilarityOptions={['cosine', 'l2']}
        engineOptions={['lucene']}
        savedEngine="lucene"
      />
    );
    await waitForControls();

    expect(document.getElementById('add-sparse-vector')).toBeNull();
    expect(screen.queryByRole('button', { name: /what is this/i })).toBeNull();
  });

  it('initializes the checkbox from the saved flag on every open', async () => {
    mockEnrich.mockResolvedValue(result());
    const { rerender } = renderWithProviders(
      <VectorDBFeatureMappingTearsheet {...baseProps} addSparseVector />
    );
    await waitForControls();
    expect(screen.getByRole('checkbox', { name: /bm25/i })).toBeChecked();

    // Toggle off, close, and reopen: the saved (true) value is restored.
    fireEvent.click(screen.getByRole('checkbox', { name: /bm25/i }));
    await waitFor(() => { expect(screen.getByRole('checkbox', { name: /bm25/i })).not.toBeChecked(); });
    rerender(<VectorDBFeatureMappingTearsheet {...baseProps} open={false} addSparseVector />);
    rerender(<VectorDBFeatureMappingTearsheet {...baseProps} open addSparseVector />);

    await waitFor(() => { expect(screen.getByRole('checkbox', { name: /bm25/i })).toBeChecked(); });
    expect(mockEnrich).toHaveBeenLastCalledWith(
      expect.anything(), 'node-1', 'weaviate', expect.anything(), 'collection_name', undefined, true
    );
  });

  it('re-requests enrichment with the new flag when toggled', async () => {
    mockEnrich.mockResolvedValue(result());
    renderWithProviders(<VectorDBFeatureMappingTearsheet {...baseProps} />);
    await waitForControls();
    mockEnrich.mockClear();

    fireEvent.click(screen.getByRole('checkbox', { name: /bm25/i }));

    await waitFor(() => { expect(mockEnrich).toHaveBeenCalledTimes(1); });
    expect(mockEnrich.mock.calls[0]?.[6]).toBe(true);
  });

  it('discards a superseded enrichment response', async () => {
    let resolveFirst: (value: VectorDBEnrichmentResult | null) => void = () => undefined;
    mockEnrich
      .mockResolvedValueOnce(result())
      .mockReturnValueOnce(new Promise((resolve) => { resolveFirst = resolve; }))
      .mockResolvedValueOnce(
        result({ feature_mappings: [{ feature_name: 'content', mapped_column_name: 'latest_column' }] })
      );
    renderWithProviders(<VectorDBFeatureMappingTearsheet {...baseProps} />);
    await waitForControls();

    fireEvent.click(screen.getByRole('checkbox', { name: /bm25/i }));
    fireEvent.click(screen.getByRole('checkbox', { name: /bm25/i }));
    await waitFor(() => { expect(document.getElementById('col-input-content')).toHaveValue('latest_column'); });

    resolveFirst(result({ feature_mappings: [{ feature_name: 'content', mapped_column_name: 'stale_column' }] }));
    await Promise.resolve();

    expect(document.getElementById('col-input-content')).toHaveValue('latest_column');
  });

  describe('keyword-searchable collection that is unsupported while the flag is off', () => {
    const unsupportedEligible = result({
      is_docpipe_supported_resource: {
        supported: false,
        reason: 'keyword-only collection with no indexed vector; enable BM25 sparse retrieval to use it',
        sparse_eligible: true,
      },
    });

    it('shows the unsupported reason and the checkbox together', async () => {
      mockEnrich.mockResolvedValue(unsupportedEligible);
      renderWithProviders(<VectorDBFeatureMappingTearsheet {...baseProps} savedResourceName="Docs" />);

      await waitFor(() => { expect(screen.getByTestId('error-empty-state')).toBeInTheDocument(); });
      expect(screen.getByTestId('error-empty-state')).toHaveTextContent(/enable BM25 sparse retrieval/i);
      expect(screen.getByRole('checkbox', { name: /bm25/i })).not.toBeChecked();
    });

    it('becomes supported after checking the checkbox re-runs enrichment', async () => {
      mockEnrich
        .mockResolvedValueOnce(unsupportedEligible)
        .mockResolvedValueOnce(result({ is_docpipe_supported_resource: { supported: true, sparse_eligible: true } }));
      renderWithProviders(<VectorDBFeatureMappingTearsheet {...baseProps} savedResourceName="Docs" />);
      await waitFor(() => { expect(screen.getByTestId('error-empty-state')).toBeInTheDocument(); });

      fireEvent.click(screen.getByRole('checkbox', { name: /bm25/i }));

      await waitFor(() => { expect(screen.queryByTestId('error-empty-state')).toBeNull(); });
      expect(mockEnrich.mock.calls[1]?.[6]).toBe(true);
      expect(screen.getByRole('checkbox', { name: /bm25/i })).toBeChecked();
    });
  });

  it('shows only the unsupported state when the collection is not BM25-eligible', async () => {
    mockEnrich.mockResolvedValue(
      result({ is_docpipe_supported_resource: { supported: false, reason: 'tokenization mismatch' } })
    );
    renderWithProviders(<VectorDBFeatureMappingTearsheet {...baseProps} savedResourceName="Docs" />);

    await waitFor(() => { expect(screen.getByTestId('error-empty-state')).toBeInTheDocument(); });
    expect(screen.getByTestId('error-empty-state')).toHaveTextContent(/tokenization mismatch/i);
    expect(document.getElementById('add-sparse-vector')).toBeNull();
  });
});

describe('VectorDBFeatureMappingTearsheet - Weaviate enrichment states', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    Element.prototype.scrollIntoView = vi.fn();
  });

  it('shows a loading indicator while enrichment is in flight', () => {
    mockEnrich.mockReturnValue(new Promise(() => undefined));
    renderWithProviders(<VectorDBFeatureMappingTearsheet {...baseProps} />);

    expect(document.getElementById('resource-select')).toBeNull();
    expect(screen.getByTestId('tearsheet-body')).toBeInTheDocument();
  });

  it('shows the thrown-error message and keeps the saved mappings usable', async () => {
    mockEnrich.mockRejectedValue(new Error('boom'));
    renderWithProviders(
      <VectorDBFeatureMappingTearsheet
        {...baseProps}
        savedResourceName="Docs"
        currentFeatureMappings={[{ feature_name: 'content', mapped_column_name: 'text', is_mandatory: true }]}
      />
    );

    await waitFor(() => { expect(screen.getByText(/failed to load available resources/i)).toBeInTheDocument(); });
    expect(document.getElementById('col-input-content')).toHaveValue('text');
  });

  it('shows the backend error for an unreachable deployment, not an unsupported collection', async () => {
    mockEnrich.mockResolvedValue(
      result({
        available_resources: [],
        feature_mappings: [],
        available_features: {},
        is_docpipe_supported_resource: { supported: false, error: 'connection refused' },
      })
    );
    renderWithProviders(<VectorDBFeatureMappingTearsheet {...baseProps} savedResourceName="Docs" />);

    await waitFor(() => {
      expect(screen.getByText('Could not read from the vector database: connection refused')).toBeInTheDocument();
    });
    expect(screen.queryByTestId('error-empty-state')).toBeNull();
  });

  it('shows no error for a reachable deployment that has no collections', async () => {
    mockEnrich.mockResolvedValue(
      result({
        available_resources: [],
        feature_mappings: [],
        available_features: {},
        is_docpipe_supported_resource: { supported: true },
      })
    );
    renderWithProviders(<VectorDBFeatureMappingTearsheet {...baseProps} />);
    await waitForControls();

    expect(screen.queryByText(/could not read from the vector database/i)).toBeNull();
    expect(screen.queryByTestId('error-empty-state')).toBeNull();
    expect(document.getElementById('new-resource-name')).toBeInTheDocument();
  });

  it('uses the generic unsupported text when the provider reports no reason', async () => {
    mockEnrich.mockResolvedValue(result({ is_docpipe_supported_resource: { supported: false } }));
    renderWithProviders(<VectorDBFeatureMappingTearsheet {...baseProps} savedResourceName="Docs" />);

    await waitFor(() => { expect(screen.getByTestId('error-empty-state')).toBeInTheDocument(); });
    expect(screen.getByTestId('error-empty-state')).toHaveTextContent(/does not have a vector field configured/i);
  });
});

describe('VectorDBFeatureMappingTearsheet - failed refresh', () => {
  const failed = result({
    available_resources: [],
    feature_mappings: [],
    available_features: {},
    is_docpipe_supported_resource: { supported: false, error: 'connection refused' },
  });
  const loaded = result({ available_resources: ['Docs', 'Other'] });

  beforeEach(() => {
    vi.clearAllMocks();
    Element.prototype.scrollIntoView = vi.fn();
  });

  const renderLoaded = async (): Promise<void> => {
    renderWithProviders(
      <VectorDBFeatureMappingTearsheet
        {...baseProps}
        savedResourceName="Docs"
        currentFeatureMappings={[{ feature_name: 'content', mapped_column_name: 'text', is_mandatory: true }]}
      />
    );
    await waitForControls();
    expect(document.getElementById('col-input-content')).toHaveValue('text');
  };

  const collectionInput = (): HTMLElement => screen.getByRole('combobox', { name: /collection name/i });

  it('keeps the previous collection and mappings when changing the collection fails', async () => {
    mockEnrich.mockResolvedValueOnce(loaded).mockResolvedValueOnce(failed);
    await renderLoaded();

    fireEvent.click(collectionInput());
    fireEvent.click(screen.getByRole('option', { name: 'Other' }));

    await waitFor(() => {
      expect(screen.getByText('Could not read from the vector database: connection refused')).toBeInTheDocument();
    });
    expect(collectionInput()).toHaveValue('Docs');
    expect(document.getElementById('col-input-content')).toHaveValue('text');
    expect(screen.queryByTestId('error-empty-state')).toBeNull();
  });

  it('saves the previous collection, not the failed one, after a failed collection change', async () => {
    mockEnrich.mockResolvedValueOnce(loaded).mockResolvedValueOnce(failed);
    await renderLoaded();
    fireEvent.click(collectionInput());
    fireEvent.click(screen.getByRole('option', { name: 'Other' }));
    await waitFor(() => { expect(screen.getByText(/connection refused/i)).toBeInTheDocument(); });

    fireEvent.click(screen.getByRole('button', { name: /^save$/i }));

    expect(baseProps.onSave).toHaveBeenCalledTimes(1);
    expect(baseProps.onSave.mock.calls[0]?.[0]).toMatchObject({ resourceName: 'Docs' });
  });

  it('locks the distance metric while a collection change is pending, so a failed refresh saves the stored metric', async () => {
    const docs = result({
      stored_resource_metadata: { vector_similarity: 'cosine', dimension_size: 3 },
    });
    let rejectRefresh: (reason: Error) => void = () => undefined;
    mockEnrich
      .mockResolvedValueOnce(docs)
      .mockReturnValueOnce(new Promise((_resolve, reject) => { rejectRefresh = reject; }));
    await renderLoaded();

    fireEvent.click(collectionInput());
    fireEvent.click(screen.getByRole('option', { name: /create new/i }));

    await waitFor(() => { expect(mockEnrich).toHaveBeenCalledTimes(2); });
    expect(screen.getByRole('combobox', { name: /distance metric/i })).toBeDisabled();

    await act(async () => { rejectRefresh(new Error('connection refused')); });
    await waitFor(() => { expect(collectionInput()).toHaveValue('Docs'); });
    fireEvent.click(screen.getByRole('button', { name: /^save$/i }));

    expect(baseProps.onSave.mock.calls[0]?.[0]).toMatchObject({
      resourceName: 'Docs',
      similarityMetric: 'cosine',
    });
  });

  it('reverts the BM25 checkbox and keeps the mappings when toggling it fails', async () => {
    mockEnrich.mockResolvedValueOnce(loaded).mockResolvedValueOnce(failed);
    await renderLoaded();

    fireEvent.click(screen.getByRole('checkbox', { name: /bm25/i }));

    await waitFor(() => {
      expect(screen.getByText('Could not read from the vector database: connection refused')).toBeInTheDocument();
    });
    expect(screen.getByRole('checkbox', { name: /bm25/i })).not.toBeChecked();
    expect(document.getElementById('col-input-content')).toHaveValue('text');
  });

  it('clears the error once a later refresh succeeds', async () => {
    mockEnrich.mockResolvedValueOnce(loaded).mockResolvedValueOnce(failed).mockResolvedValueOnce(loaded);
    await renderLoaded();
    fireEvent.click(screen.getByRole('checkbox', { name: /bm25/i }));
    await waitFor(() => { expect(screen.getByText(/connection refused/i)).toBeInTheDocument(); });

    fireEvent.click(screen.getByRole('checkbox', { name: /bm25/i }));

    await waitFor(() => { expect(screen.queryByText(/connection refused/i)).toBeNull(); });
    expect(screen.getByRole('checkbox', { name: /bm25/i })).toBeChecked();
  });

  it('blocks saving when the initial load reports a provider error', async () => {
    mockEnrich.mockResolvedValue(failed);
    renderWithProviders(<VectorDBFeatureMappingTearsheet {...baseProps} savedResourceName="Docs" />);

    await waitFor(() => { expect(screen.getByText(/connection refused/i)).toBeInTheDocument(); });

    expect(screen.getByRole('button', { name: /^save$/i })).toBeDisabled();
  });

  it('restores the last enriched collection when a later overlapping change fails', async () => {
    const loadedThree = result({ available_resources: ['Docs', 'Other', 'Third'] });
    mockEnrich
      .mockResolvedValueOnce(loadedThree)
      .mockReturnValueOnce(new Promise(() => undefined))
      .mockResolvedValueOnce(failed);
    await renderLoaded();

    fireEvent.click(collectionInput());
    fireEvent.click(screen.getByRole('option', { name: 'Other' }));
    fireEvent.click(collectionInput());
    fireEvent.click(screen.getByRole('option', { name: 'Third' }));

    await waitFor(() => { expect(screen.getByText(/connection refused/i)).toBeInTheDocument(); });
    expect(collectionInput()).toHaveValue('Docs');
    expect(document.getElementById('col-input-content')).toHaveValue('text');

    fireEvent.click(screen.getByRole('button', { name: /^save$/i }));

    expect(baseProps.onSave.mock.calls[0]?.[0]).toMatchObject({ resourceName: 'Docs' });
  });

  it('restores the last enriched BM25 state when an overlapping toggle fails', async () => {
    mockEnrich
      .mockResolvedValueOnce(loaded)
      .mockReturnValueOnce(new Promise(() => undefined))
      .mockResolvedValueOnce(failed);
    await renderLoaded();

    fireEvent.click(screen.getByRole('checkbox', { name: /bm25/i }));
    fireEvent.click(screen.getByRole('checkbox', { name: /bm25/i }));

    await waitFor(() => { expect(screen.getByText(/connection refused/i)).toBeInTheDocument(); });
    expect(screen.getByRole('checkbox', { name: /bm25/i })).not.toBeChecked();

    fireEvent.click(screen.getByRole('button', { name: /^save$/i }));

    expect(baseProps.onSave.mock.calls[0]?.[0]).toMatchObject({ addSparseVector: false });
  });

  it('restores the last enriched collection and flag when an enrichment request throws', async () => {
    mockEnrich.mockResolvedValueOnce(loaded).mockRejectedValueOnce(new Error('boom'));
    await renderLoaded();

    fireEvent.click(collectionInput());
    fireEvent.click(screen.getByRole('option', { name: 'Other' }));

    await waitFor(() => { expect(screen.getByText(/failed to load/i)).toBeInTheDocument(); });
    expect(collectionInput()).toHaveValue('Docs');
    expect(document.getElementById('col-input-content')).toHaveValue('text');
  });
});

describe('VectorDBFeatureMappingTearsheet - overlapping Weaviate refreshes', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    Element.prototype.scrollIntoView = vi.fn();
  });

  it('saves the metric of the displayed collection when a BM25 toggle supersedes a collection change', async () => {
    const docs = result({
      available_resources: ['Docs', 'Other'],
      stored_resource_metadata: { vector_similarity: 'cosine', dimension_size: 3 },
    });
    const other = result({
      available_resources: ['Docs', 'Other'],
      stored_resource_metadata: { vector_similarity: 'dot', dimension_size: 3 },
    });
    mockEnrich
      .mockResolvedValueOnce(docs)
      .mockReturnValueOnce(new Promise(() => undefined))
      .mockResolvedValueOnce(other);
    renderWithProviders(
      <VectorDBFeatureMappingTearsheet
        {...baseProps}
        savedResourceName="Docs"
        currentFeatureMappings={[{ feature_name: 'content', mapped_column_name: 'text', is_mandatory: true }]}
      />
    );
    await waitForControls();

    fireEvent.click(screen.getByRole('combobox', { name: /collection name/i }));
    fireEvent.click(screen.getByRole('option', { name: 'Other' }));
    fireEvent.click(screen.getByRole('checkbox', { name: /bm25/i }));

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /^save$/i })).not.toBeDisabled();
    });
    fireEvent.click(screen.getByRole('button', { name: /^save$/i }));

    expect(baseProps.onSave.mock.calls[0]?.[0]).toMatchObject({
      resourceName: 'Other',
      similarityMetric: 'dot',
      addSparseVector: true,
    });
  });

  it('keeps the metric chosen for a new collection when BM25 is toggled', async () => {
    mockEnrich.mockResolvedValue(result());
    renderWithProviders(<VectorDBFeatureMappingTearsheet {...baseProps} />);
    await waitForControls();

    fireEvent.change(document.getElementById('new-resource-name') as HTMLElement, { target: { value: 'NewDocs' } });
    fireEvent.click(screen.getByRole('combobox', { name: /distance metric/i }));
    fireEvent.click(screen.getByRole('option', { name: 'Dot product' }));
    fireEvent.click(screen.getByRole('checkbox', { name: /bm25/i }));

    await waitFor(() => { expect(mockEnrich).toHaveBeenCalledTimes(2); });
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /^save$/i })).not.toBeDisabled();
    });
    fireEvent.click(screen.getByRole('button', { name: /^save$/i }));

    expect(baseProps.onSave.mock.calls[0]?.[0]).toMatchObject({
      resourceName: 'NewDocs',
      similarityMetric: 'dot',
      addSparseVector: true,
    });
  });
});

describe('VectorDBFeatureMappingTearsheet - OpenSearch and Milvus refresh behavior is unchanged', () => {
  const loaded = result({
    available_resources: ['Docs', 'Other'],
    stored_resource_metadata: { vector_similarity: 'IP', dimension_size: 3 },
  });
  const milvusProps = {
    ...baseProps,
    provider: 'milvus',
    providerCfg: getProviderConfig('milvus'),
    vectorSimilarityOptions: ['L2', 'IP', 'COSINE'],
    savedVectorSimilarity: 'L2',
    savedResourceName: 'Docs',
    currentFeatureMappings: [{ feature_name: 'content', mapped_column_name: 'text', is_mandatory: true }],
  };
  const opensearchProps = {
    ...baseProps,
    provider: 'opensearch',
    providerCfg: getProviderConfig('opensearch'),
    vectorSimilarityOptions: ['cosine', 'l2'],
    engineOptions: ['lucene'],
    savedEngine: 'lucene',
    savedResourceName: 'Docs',
    currentFeatureMappings: [{ feature_name: 'content', mapped_column_name: 'text', is_mandatory: true }],
  };

  beforeEach(() => {
    vi.clearAllMocks();
    Element.prototype.scrollIntoView = vi.fn();
  });

  const collectionInput = (): HTMLElement => screen.getByRole('combobox', { name: /name/i });

  it('keeps the chosen index selected after a failed refresh for OpenSearch', async () => {
    mockEnrich.mockResolvedValueOnce(loaded).mockRejectedValueOnce(new Error('boom'));
    renderWithProviders(<VectorDBFeatureMappingTearsheet {...opensearchProps} />);
    await waitForControls();

    fireEvent.click(collectionInput());
    fireEvent.click(screen.getByRole('option', { name: 'Other' }));

    await waitFor(() => { expect(screen.getByText(/failed to load/i)).toBeInTheDocument(); });
    expect(collectionInput()).toHaveValue('Other');
  });

  it('keeps the chosen index selected when the response carries an error for OpenSearch', async () => {
    const failed = result({
      available_resources: [],
      feature_mappings: [],
      available_features: {},
      is_docpipe_supported_resource: { supported: false, error: 'connection refused' },
    });
    mockEnrich.mockResolvedValueOnce(loaded).mockResolvedValueOnce(failed);
    renderWithProviders(<VectorDBFeatureMappingTearsheet {...opensearchProps} />);
    await waitForControls();

    fireEvent.click(collectionInput());
    fireEvent.click(screen.getByRole('option', { name: 'Other' }));

    await waitFor(() => { expect(screen.getByText(/connection refused/i)).toBeInTheDocument(); });
    expect(collectionInput()).toHaveValue('Other');
  });

  it('keeps the sparse checkbox as toggled after a failed refresh for Milvus', async () => {
    mockEnrich.mockResolvedValueOnce(loaded).mockRejectedValueOnce(new Error('boom'));
    renderWithProviders(<VectorDBFeatureMappingTearsheet {...milvusProps} />);
    await waitForControls();

    fireEvent.click(screen.getByRole('checkbox', { name: /sparse vectors for hybrid search/i }));

    await waitFor(() => { expect(screen.getByText(/failed to reload/i)).toBeInTheDocument(); });
    expect(screen.getByRole('checkbox', { name: /sparse vectors for hybrid search/i })).toBeChecked();
  });

  it('leaves the Milvus metric untouched when the sparse flag is toggled', async () => {
    const toggled = result({
      available_resources: ['Docs', 'Other'],
      stored_resource_metadata: { vector_similarity: 'COSINE', dimension_size: 3 },
    });
    mockEnrich.mockResolvedValueOnce(loaded).mockResolvedValueOnce(toggled);
    renderWithProviders(<VectorDBFeatureMappingTearsheet {...milvusProps} />);
    await waitForControls();

    fireEvent.click(screen.getByRole('checkbox', { name: /sparse vectors for hybrid search/i }));
    await waitFor(() => { expect(mockEnrich).toHaveBeenCalledTimes(2); });
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /^save$/i })).not.toBeDisabled();
    });
    fireEvent.click(screen.getByRole('button', { name: /^save$/i }));

    expect(baseProps.onSave.mock.calls[0]?.[0]).toMatchObject({ similarityMetric: 'IP', addSparseVector: true });
  });
});
