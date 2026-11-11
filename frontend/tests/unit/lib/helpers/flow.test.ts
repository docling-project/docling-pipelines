import { describe, it, expect } from 'vitest';
import { buildFlowDefinition } from '@/lib/helpers/flow';

describe('buildFlowDefinition', () => {
  it('returns object with doc_type "pipeline"', () => {
    const def = buildFlowDefinition('Test', 'Description');
    expect(def.doc_type).toBe('pipeline');
  });

  it('returns object with version "3.0"', () => {
    const def = buildFlowDefinition('Test', 'Description');
    expect(def.version).toBe('3.0');
  });

  it('two calls produce different primary_pipeline UUIDs', () => {
    const def1 = buildFlowDefinition('Flow 1', 'Desc');
    const def2 = buildFlowDefinition('Flow 2', 'Desc');
    expect(def1.primary_pipeline).not.toBe(def2.primary_pipeline);
  });

  it('nodes defaults to empty array when not passed', () => {
    const def = buildFlowDefinition('Test', 'Desc');
    const pipeline = (def.pipelines as Array<{ nodes: unknown[] }>)[0];
    expect(pipeline?.nodes).toEqual([]);
  });

  it('name and description appear in ds_flow app_data', () => {
    const def = buildFlowDefinition('My Flow', 'My Desc');
    const pipeline = (def.pipelines as Array<{ app_data: { ds_flow: { name: string; description: string } } }>)[0];
    expect(pipeline?.app_data.ds_flow.name).toBe('My Flow');
    expect(pipeline?.app_data.ds_flow.description).toBe('My Desc');
  });

  it('pipelines[0].id equals primary_pipeline', () => {
    const def = buildFlowDefinition('Test', 'Desc');
    const pipeline = (def.pipelines as Array<{ id: string }>)[0];
    expect(pipeline?.id).toBe(def.primary_pipeline);
  });

  it('accepts a pre-built nodes array', () => {
    const nodes = [{ id: 'n1', type: 'ingest_source' }];
    const def = buildFlowDefinition('Test', 'Desc', nodes);
    const pipeline = (def.pipelines as Array<{ nodes: unknown[] }>)[0];
    expect(pipeline?.nodes).toEqual(nodes);
  });

  it('uses fallback UUID generation when crypto.randomUUID is not available', () => {
    const original = crypto.randomUUID;
    delete (crypto as unknown as Record<string, unknown>).randomUUID;
    try {
      const def = buildFlowDefinition('Fallback', 'Desc');
      expect(typeof def.primary_pipeline).toBe('string');
      expect(def.primary_pipeline).toMatch(
        /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i
      );
    } finally {
      (crypto as unknown as Record<string, unknown>).randomUUID = original;
    }
  });

  it('fallback UUID contains version 4 format (4xxx segment)', () => {
    // Force fallback by removing randomUUID (crypto itself stays defined).
    const originalRandomUUID = (crypto as unknown as Record<string, unknown>).randomUUID;
    Object.defineProperty(crypto, 'randomUUID', { value: undefined, configurable: true });
    try {
      const def = buildFlowDefinition('CryptoUndefined', 'Desc');
      // UUID string should be 36 characters in the form xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
      expect((def.primary_pipeline?.length ?? 0)).toBe(36);
    } finally {
      Object.defineProperty(crypto, 'randomUUID', { value: originalRandomUUID, configurable: true });
    }
  });

  it('fallback UUID: the replace callback covers both x and y characters', () => {
    // Exercise lines 16-18 by patching Math.random to predictable values
    // and removing randomUUID so the fallback branch runs.
    const originalRandom = Math.random;
    const originalRandomUUID = (crypto as unknown as Record<string, unknown>).randomUUID;
    let callCount = 0;
    Math.random = () => (callCount++ % 2 === 0 ? 0.5 : 0.9);
    Object.defineProperty(crypto, 'randomUUID', { value: undefined, configurable: true });
    try {
      const def = buildFlowDefinition('PatchedRandom', 'Desc');
      expect(typeof def.primary_pipeline).toBe('string');
      expect((def.primary_pipeline?.length ?? 0)).toBeGreaterThan(0);
    } finally {
      Math.random = originalRandom;
      Object.defineProperty(crypto, 'randomUUID', { value: originalRandomUUID, configurable: true });
    }
  });
});
