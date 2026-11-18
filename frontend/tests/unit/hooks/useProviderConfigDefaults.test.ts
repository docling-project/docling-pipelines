import { describe, it, expect, vi } from 'vitest';
import { renderHook } from '@testing-library/react';
import { useProviderConfigDefaults } from '@/hooks/useProviderConfigDefaults';
import type { OperatorFeature } from '@/types';
import { NodeOperator } from '@/constants/operators';

function makeController(nodeOp: string, values: Record<string, unknown> = {}) {
  const updatePropertyValue = vi.fn();

  const getPropertyValue = vi.fn((param: { name: string }) => values[param.name]);

  const getAppData = vi.fn(() => ({
    nodeId: 'node-1',
    pipelineFlow: {
      pipelines: [{ nodes: [{ id: 'node-1', op: nodeOp }] }],
    },
  }));

  return { getPropertyValue, updatePropertyValue, getAppData };
}

// Shared provider schema helpers

// Builds a minimal provider schema with two fields that both have defaults.
function makeProviderSchema(): OperatorFeature {
  return {
    type: 'json',
    properties: {
      model_id: { type: 'string', default: 'granite' },
      temperature: { type: 'double', default: 0 },
    },
  };
}

// Builds a provider schema where NO field has a default (buildDefaults returns {}).
function makeEmptyDefaultsSchema(): OperatorFeature {
  return {
    type: 'json',
    properties: {
      model_id: { type: 'string' }, // no default key
    },
  };
}

// Flat layout tests (ingest_source, embeddings)

describe('useProviderConfigDefaults — flat layout', () => {
  it('seeds provider_config defaults for ingest_source when config is empty', () => {
    const nodeAttributes: Record<string, OperatorFeature> = {
      provider_config: {
        type: 'json',
        providers: { filesystem: makeProviderSchema() },
      },
    };
    const controller = makeController(NodeOperator.INGEST_SOURCE, {
      provider: 'filesystem',
      provider_config: undefined,
    });

    renderHook(() => useProviderConfigDefaults(controller, nodeAttributes));

    expect(controller.updatePropertyValue).toHaveBeenCalledWith(
      { name: 'provider_config' },
      { model_id: 'granite', temperature: 0 }
    );
  });

  it('does not overwrite provider_config when it already has values for ingest_source', () => {
    const nodeAttributes: Record<string, OperatorFeature> = {
      provider_config: {
        type: 'json',
        providers: { filesystem: makeProviderSchema() },
      },
    };
    const controller = makeController(NodeOperator.INGEST_SOURCE, {
      provider: 'filesystem',
      provider_config: { model_id: 'user-set' },
    });

    renderHook(() => useProviderConfigDefaults(controller, nodeAttributes));

    expect(controller.updatePropertyValue).not.toHaveBeenCalled();
  });

  it('seeds provider_config defaults for embeddings', () => {
    const nodeAttributes: Record<string, OperatorFeature> = {
      provider_config: {
        type: 'json',
        providers: { litellm: makeProviderSchema() },
      },
    };
    const controller = makeController(NodeOperator.EMBEDDINGS, {
      provider: 'litellm',
      provider_config: null,
    });

    renderHook(() => useProviderConfigDefaults(controller, nodeAttributes));

    expect(controller.updatePropertyValue).toHaveBeenCalledWith(
      { name: 'provider_config' },
      { model_id: 'granite', temperature: 0 }
    );
  });

  it('does not call updatePropertyValue when no provider is active', () => {
    const nodeAttributes: Record<string, OperatorFeature> = {
      provider_config: {
        type: 'json',
        providers: { litellm: makeProviderSchema() },
      },
    };
    const controller = makeController(NodeOperator.EMBEDDINGS, {
      provider: '',
      provider_config: undefined,
    });

    renderHook(() => useProviderConfigDefaults(controller, nodeAttributes));

    expect(controller.updatePropertyValue).not.toHaveBeenCalled();
  });

  it('does not call updatePropertyValue when provider schema has no properties', () => {
    const nodeAttributes: Record<string, OperatorFeature> = {
      provider_config: {
        type: 'json',
        providers: { litellm: { type: 'json' } }, // no properties key
      },
    };
    const controller = makeController(NodeOperator.EMBEDDINGS, {
      provider: 'litellm',
      provider_config: undefined,
    });

    renderHook(() => useProviderConfigDefaults(controller, nodeAttributes));

    expect(controller.updatePropertyValue).not.toHaveBeenCalled();
  });

  it('does not call updatePropertyValue when all schema properties lack a default', () => {
    const nodeAttributes: Record<string, OperatorFeature> = {
      provider_config: {
        type: 'json',
        providers: { litellm: makeEmptyDefaultsSchema() },
      },
    };
    const controller = makeController(NodeOperator.EMBEDDINGS, {
      provider: 'litellm',
      provider_config: undefined,
    });

    renderHook(() => useProviderConfigDefaults(controller, nodeAttributes));

    expect(controller.updatePropertyValue).not.toHaveBeenCalled();
  });
});

// Nested layout tests (extract_operator, chunker, storage_output)

describe('useProviderConfigDefaults — nested layout', () => {
  it('seeds text_extraction.provider_config for extract_operator', () => {
    const nodeAttributes: Record<string, OperatorFeature> = {
      text_extraction: {
        type: 'json',
        properties: {
          provider: { type: 'string' },
          provider_config: {
            type: 'json',
            providers: { docling_library: makeProviderSchema() },
          },
        },
      },
      entity_extraction: { type: 'json', properties: {} },
    };
    const controller = makeController(NodeOperator.EXTRACT, {
      text_extraction: { provider: 'docling_library', provider_config: undefined },
      entity_extraction: { provider: 'none' },
    });

    renderHook(() => useProviderConfigDefaults(controller, nodeAttributes));

    expect(controller.updatePropertyValue).toHaveBeenCalledWith(
      { name: 'text_extraction' },
      expect.objectContaining({ provider_config: { model_id: 'granite', temperature: 0 } })
    );
  });

  it('seeds entity_extraction.provider_config for extract_operator', () => {
    const nodeAttributes: Record<string, OperatorFeature> = {
      text_extraction: { type: 'json', properties: {} },
      entity_extraction: {
        type: 'json',
        properties: {
          provider: { type: 'string' },
          provider_config: {
            type: 'json',
            providers: { litellm: makeProviderSchema() },
          },
        },
      },
    };
    const controller = makeController(NodeOperator.EXTRACT, {
      text_extraction: { provider: '' },
      entity_extraction: { provider: 'litellm', provider_config: null },
    });

    renderHook(() => useProviderConfigDefaults(controller, nodeAttributes));

    expect(controller.updatePropertyValue).toHaveBeenCalledWith(
      { name: 'entity_extraction' },
      expect.objectContaining({ provider_config: { model_id: 'granite', temperature: 0 } })
    );
  });

  it('does not overwrite text_extraction.provider_config when already populated', () => {
    const nodeAttributes: Record<string, OperatorFeature> = {
      text_extraction: {
        type: 'json',
        properties: {
          provider: { type: 'string' },
          provider_config: {
            type: 'json',
            providers: { docling_library: makeProviderSchema() },
          },
        },
      },
      entity_extraction: { type: 'json', properties: {} },
    };
    const controller = makeController(NodeOperator.EXTRACT, {
      text_extraction: {
        provider: 'docling_library',
        provider_config: { model_id: 'already-set' },
      },
      entity_extraction: { provider: '' },
    });

    renderHook(() => useProviderConfigDefaults(controller, nodeAttributes));

    expect(controller.updatePropertyValue).not.toHaveBeenCalledWith(
      { name: 'text_extraction' },
      expect.anything()
    );
  });

  it('seeds summarization.provider_config for chunker', () => {
    const nodeAttributes: Record<string, OperatorFeature> = {
      summarization: {
        type: 'json',
        properties: {
          provider: { type: 'string' },
          provider_config: {
            type: 'json',
            providers: { litellm: makeProviderSchema() },
          },
        },
      },
    };
    const controller = makeController(NodeOperator.CHUNKER, {
      summarization: { provider: 'litellm', provider_config: {} },
    });

    renderHook(() => useProviderConfigDefaults(controller, nodeAttributes));

    expect(controller.updatePropertyValue).toHaveBeenCalledWith(
      { name: 'summarization' },
      expect.objectContaining({ provider_config: { model_id: 'granite', temperature: 0 } })
    );
  });

  it('seeds destination_config.provider_config for storage_output', () => {
    const nodeAttributes: Record<string, OperatorFeature> = {
      destination_config: {
        type: 'json',
        properties: {
          provider: { type: 'string' },
          provider_config: {
            type: 'json',
            providers: { filesystem: makeProviderSchema() },
          },
        },
      },
    };
    const controller = makeController(NodeOperator.STORAGE_OUTPUT, {
      destination_config: { provider: 'filesystem', provider_config: undefined },
    });

    renderHook(() => useProviderConfigDefaults(controller, nodeAttributes));

    expect(controller.updatePropertyValue).toHaveBeenCalledWith(
      { name: 'destination_config' },
      expect.objectContaining({ provider_config: { model_id: 'granite', temperature: 0 } })
    );
  });

  it('does not call updatePropertyValue when nested provider is absent', () => {
    const nodeAttributes: Record<string, OperatorFeature> = {
      summarization: {
        type: 'json',
        properties: {
          provider_config: {
            type: 'json',
            providers: { litellm: makeProviderSchema() },
          },
        },
      },
    };
    const controller = makeController(NodeOperator.CHUNKER, {
      summarization: { provider_config: undefined }, // no provider key
    });

    renderHook(() => useProviderConfigDefaults(controller, nodeAttributes));

    expect(controller.updatePropertyValue).not.toHaveBeenCalled();
  });
});

// Guard tests

describe('useProviderConfigDefaults — guards', () => {
  it('does nothing when controller is null', () => {
    const nodeAttributes: Record<string, OperatorFeature> = {
      provider_config: { type: 'json', providers: { litellm: makeProviderSchema() } },
    };
    // Should not throw
    expect(() => {
      renderHook(() => useProviderConfigDefaults(null, nodeAttributes));
    }).not.toThrow();
  });

  it('does nothing when nodeAttributes is empty', () => {
    const controller = makeController(NodeOperator.EMBEDDINGS, { provider: 'litellm' });
    renderHook(() => useProviderConfigDefaults(controller, {}));
    expect(controller.updatePropertyValue).not.toHaveBeenCalled();
  });

  it('does nothing for an unrecognized operator', () => {
    const nodeAttributes: Record<string, OperatorFeature> = {
      provider_config: { type: 'json', providers: { litellm: makeProviderSchema() } },
    };
    const controller = makeController('unknown_op', { provider: 'litellm' });
    renderHook(() => useProviderConfigDefaults(controller, nodeAttributes));
    expect(controller.updatePropertyValue).not.toHaveBeenCalled();
  });
});
