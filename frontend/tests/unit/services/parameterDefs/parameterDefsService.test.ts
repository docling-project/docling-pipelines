import { describe, it, expect, vi, afterEach } from 'vitest';
import { getParameterDef } from '@/services/parameterDefs/parameterDefsService';

describe('parameterDefsService', () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('returns parsed paramDef on successful fetch', async () => {
    const mockDef = {
      parameters: [{ id: 'chunk_size', type: 'integer' }],
      uihints: { group_info: [] },
    };
    vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(
      new Response(JSON.stringify(mockDef), { status: 200 })
    );
    const result = await getParameterDef({ operatorName: 'chunker' });
    expect(result.parameters).toHaveLength(1);
    expect(result.parameters[0]?.id).toBe('chunk_size');
  });

  it('returns fallback paramDef when fetch returns 404', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(
      new Response('Not Found', { status: 404 })
    );
    const result = await getParameterDef({ operatorName: 'unknown_operator' });
    expect(result.parameters).toEqual([]);
    expect(result.uihints.group_info[0]?.type).toBe('customPanel');
  });

  it('returns fallback paramDef when fetch throws', async () => {
    vi.spyOn(globalThis, 'fetch').mockRejectedValueOnce(new Error('Network error'));
    const result = await getParameterDef({ operatorName: 'chunker' });
    expect(result.parameters).toEqual([]);
  });

  it('calls the correct URL', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(
      new Response(JSON.stringify({ parameters: [], uihints: { group_info: [] } }), { status: 200 })
    );
    await getParameterDef({ operatorName: 'embeddings' });
    expect(fetchSpy).toHaveBeenCalledWith(
      '/ui/parameterDefs/embeddings_paramDef.json',
      expect.objectContaining({ method: 'GET' })
    );
  });
});
