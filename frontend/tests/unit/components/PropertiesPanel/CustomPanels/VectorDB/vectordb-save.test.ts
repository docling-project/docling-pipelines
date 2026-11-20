import { describe, it, expect } from 'vitest';
import { mergeProviderConfig, clearProviderConfigResource } from '@/components/PropertiesPanel/CustomPanels/VectorDB';

describe('vectordb-save', () => {
  describe('mergeProviderConfig', () => {
    it('merges patch into existing config', () => {
      const result = mergeProviderConfig('{"host":"localhost"}', { index_name: 'my-index' });
      expect(result).toEqual({ host: 'localhost', index_name: 'my-index' });
    });

    it('returns patch when config JSON is empty object', () => {
      const result = mergeProviderConfig('{}', { index_name: 'idx' });
      expect(result).toEqual({ index_name: 'idx' });
    });

    it('handles invalid JSON gracefully', () => {
      const result = mergeProviderConfig('not-json', { key: 'val' });
      expect(result).toEqual({ key: 'val' });
    });

    it('patch values overwrite existing keys', () => {
      const result = mergeProviderConfig('{"host":"old"}', { host: 'new' });
      expect(result.host).toBe('new');
    });
  });

  describe('clearProviderConfigResource', () => {
    // clearProviderConfigResource takes a PARSED object, not a JSON string
    it('removes the resource name key from a parsed config object', () => {
      const config = { index_name: 'my-idx', host: 'h' };
      const result = clearProviderConfigResource(config, 'index_name');
      expect(result).not.toHaveProperty('index_name');
      expect(result).toHaveProperty('host', 'h');
    });

    it('returns object without the key when it does not exist', () => {
      const config = { host: 'h' };
      const result = clearProviderConfigResource(config, 'index_name');
      expect(result).toEqual({ host: 'h' });
    });

    it('returns empty object when only key is removed', () => {
      const result = clearProviderConfigResource({ index_name: 'x' }, 'index_name');
      expect(result).toEqual({});
    });
  });
});
