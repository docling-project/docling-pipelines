import { describe, it, expect } from 'vitest';
import {
  generateConditionId,
  conditionToText,
  isValidJSON,
  LOGICAL,
  SQL_OPERATORS,
  FEATURE_TYPES,
  NUMERIC_TYPES,
  OPERATORS_BY_TYPE,
  DATETIME_PLACEHOLDER,
  TIMESTAMP_REGEX,
} from '@/components/PropertiesPanel/CustomPanels/AnnotationFilter';

describe('conditionTypes', () => {

  // ── generateConditionId ────────────────────────────────────────────────────

  describe('generateConditionId', () => {
    it('generates a unique string id', () => {
      const id1 = generateConditionId();
      const id2 = generateConditionId();
      expect(typeof id1).toBe('string');
      expect(id1.length).toBeGreaterThan(0);
      expect(id1).not.toBe(id2);
    });

    it('starts with "cond-"', () => {
      const id = generateConditionId();
      expect(id.startsWith('cond-')).toBe(true);
    });

    it('contains a timestamp portion', () => {
      const before = Date.now();
      const id = generateConditionId();
      const after = Date.now();
      // extract the numeric portion between "cond-" and the final hex segment
      const parts = id.split('-');
      // parts[0] = "cond", parts[1] = timestamp, parts[2..] = hex
      const ts = Number(parts[1]);
      expect(ts).toBeGreaterThanOrEqual(before);
      expect(ts).toBeLessThanOrEqual(after);
    });
  });

  // ── conditionToText ────────────────────────────────────────────────────────

  describe('conditionToText', () => {
    it('formats a basic numeric condition', () => {
      const text = conditionToText({ id: '1', variable: 'lang_score', operator: '>=', value: '0.5' });
      expect(text).toBe('lang_score >= 0.5');
    });

    it('formats a string equality condition', () => {
      const text = conditionToText({ id: '2', variable: 'doc_name', operator: '==', value: 'report' });
      expect(text).toBe('doc_name == report');
    });

    it('handles null-check operator with empty value', () => {
      const text = conditionToText({ id: '3', variable: 'field', operator: 'is null', value: '' });
      expect(text).toBe('field is null ');
    });

    it('handles "is not null" operator', () => {
      const text = conditionToText({ id: '4', variable: 'field', operator: 'is not null', value: '' });
      expect(text).toBe('field is not null ');
    });

    it('includes all three parts: variable, operator, value', () => {
      const text = conditionToText({ id: '5', variable: 'pii', operator: '<', value: '0.1' });
      expect(text).toContain('pii');
      expect(text).toContain('<');
      expect(text).toContain('0.1');
    });
  });

  // ── isValidJSON ────────────────────────────────────────────────────────────

  describe('isValidJSON', () => {
    it('returns true for a valid JSON object string', () => {
      expect(isValidJSON('{"key": "value"}')).toBe(true);
    });

    it('returns true for a valid JSON array string', () => {
      expect(isValidJSON('[1,2,3]')).toBe(true);
    });

    it('returns true for a JSON number', () => {
      expect(isValidJSON('42')).toBe(true);
    });

    it('returns true for a JSON null', () => {
      expect(isValidJSON('null')).toBe(true);
    });

    it('returns true for a JSON boolean', () => {
      expect(isValidJSON('true')).toBe(true);
    });

    it('returns false for an invalid JSON string', () => {
      expect(isValidJSON('not-json')).toBe(false);
    });

    it('returns false for a truncated JSON object', () => {
      expect(isValidJSON('{key: value')).toBe(false);
    });

    it('returns false for an empty string', () => {
      expect(isValidJSON('')).toBe(false);
    });
  });

  // ── LOGICAL ────────────────────────────────────────────────────────────────

  describe('LOGICAL', () => {
    it('exports AND constant', () => {
      expect(LOGICAL.AND).toBe('AND');
    });

    it('exports OR constant', () => {
      expect(LOGICAL.OR).toBe('OR');
    });
  });

  // ── SQL_OPERATORS ─────────────────────────────────────────────────────────

  describe('SQL_OPERATORS', () => {
    it('is a non-empty array', () => {
      expect(Array.isArray(SQL_OPERATORS)).toBe(true);
      expect(SQL_OPERATORS.length).toBeGreaterThan(0);
    });

    it('each operator has label and value', () => {
      SQL_OPERATORS.forEach((op) => {
        expect(op).toHaveProperty('label');
        expect(op).toHaveProperty('value');
      });
    });

    it('includes common comparison operators', () => {
      const values = SQL_OPERATORS.map((o) => o.value);
      expect(values).toContain('==');
      expect(values).toContain('!=');
      expect(values).toContain('>=');
      expect(values).toContain('<=');
      expect(values).toContain('>');
      expect(values).toContain('<');
    });

    it('includes null-check operators', () => {
      const values = SQL_OPERATORS.map((o) => o.value);
      expect(values).toContain('is null');
      expect(values).toContain('is not null');
    });

    it('includes set membership operators', () => {
      const values = SQL_OPERATORS.map((o) => o.value);
      expect(values).toContain('in');
      expect(values).toContain('not in');
    });

    it('includes LIKE operators', () => {
      const values = SQL_OPERATORS.map((o) => o.value);
      expect(values).toContain('like');
      expect(values).toContain('not like');
    });

    it('includes between operator', () => {
      const values = SQL_OPERATORS.map((o) => o.value);
      expect(values).toContain('between');
    });
  });

  // ── FEATURE_TYPES ─────────────────────────────────────────────────────────

  describe('FEATURE_TYPES', () => {
    it('exports expected type constants', () => {
      expect(FEATURE_TYPES.BOOLEAN).toBe('boolean');
      expect(FEATURE_TYPES.BOOL).toBe('bool');
      expect(FEATURE_TYPES.DATETIME).toBe('datetime');
      expect(FEATURE_TYPES.JSON).toBe('json');
      expect(FEATURE_TYPES.INT32).toBe('int32');
      expect(FEATURE_TYPES.INT64).toBe('int64');
      expect(FEATURE_TYPES.FLOAT).toBe('float');
    });
  });

  // ── NUMERIC_TYPES ──────────────────────────────────────────────────────────

  describe('NUMERIC_TYPES', () => {
    it('contains int32, int64, float', () => {
      expect(NUMERIC_TYPES).toContain('int32');
      expect(NUMERIC_TYPES).toContain('int64');
      expect(NUMERIC_TYPES).toContain('float');
    });

    it('does not include string or boolean', () => {
      expect(NUMERIC_TYPES).not.toContain('string');
      expect(NUMERIC_TYPES).not.toContain('boolean');
    });
  });

  // ── OPERATORS_BY_TYPE ──────────────────────────────────────────────────────

  describe('OPERATORS_BY_TYPE', () => {
    it('has entries for all expected types', () => {
      expect(OPERATORS_BY_TYPE).toHaveProperty('string');
      expect(OPERATORS_BY_TYPE).toHaveProperty('float');
      expect(OPERATORS_BY_TYPE).toHaveProperty('int32');
      expect(OPERATORS_BY_TYPE).toHaveProperty('int64');
      expect(OPERATORS_BY_TYPE).toHaveProperty('bool');
      expect(OPERATORS_BY_TYPE).toHaveProperty('boolean');
      expect(OPERATORS_BY_TYPE).toHaveProperty('datetime');
      expect(OPERATORS_BY_TYPE).toHaveProperty('json');
      expect(OPERATORS_BY_TYPE).toHaveProperty('default');
    });

    it('float type includes numeric comparison operators', () => {
      const ops = OPERATORS_BY_TYPE['float']!;
      expect(ops).toContain('>=');
      expect(ops).toContain('<=');
      expect(ops).toContain('>');
      expect(ops).toContain('<');
    });

    it('boolean type does not include comparison operators', () => {
      const ops = OPERATORS_BY_TYPE['boolean']!;
      expect(ops).not.toContain('>');
      expect(ops).not.toContain('<');
    });

    it('string type includes like/not like operators', () => {
      const ops = OPERATORS_BY_TYPE['string']!;
      expect(ops).toContain('like');
      expect(ops).toContain('not like');
    });

    it('json type only allows equality and null checks', () => {
      const ops = OPERATORS_BY_TYPE['json']!;
      expect(ops).toContain('==');
      expect(ops).toContain('is null');
      expect(ops).not.toContain('>');
    });
  });

  // ── DATETIME_PLACEHOLDER ───────────────────────────────────────────────────

  describe('DATETIME_PLACEHOLDER', () => {
    it('is a non-empty string', () => {
      expect(typeof DATETIME_PLACEHOLDER).toBe('string');
      expect(DATETIME_PLACEHOLDER.length).toBeGreaterThan(0);
    });

    it('has the expected format hint', () => {
      expect(DATETIME_PLACEHOLDER).toBe('YYYY-MM-DD HH:MM:SS');
    });
  });

  // ── TIMESTAMP_REGEX ────────────────────────────────────────────────────────

  describe('TIMESTAMP_REGEX', () => {
    it('matches a valid timestamp string', () => {
      expect(TIMESTAMP_REGEX.test('2024-01-15 14:30:00')).toBe(true);
    });

    it('matches midnight time', () => {
      expect(TIMESTAMP_REGEX.test('2024-12-31 00:00:00')).toBe(true);
    });

    it('does not match a date-only string', () => {
      expect(TIMESTAMP_REGEX.test('2024-01-15')).toBe(false);
    });

    it('does not match an ISO string with T separator', () => {
      expect(TIMESTAMP_REGEX.test('2024-01-15T14:30:00')).toBe(false);
    });

    it('does not match an empty string', () => {
      expect(TIMESTAMP_REGEX.test('')).toBe(false);
    });

    it('does not match a plain English date', () => {
      expect(TIMESTAMP_REGEX.test('January 15 2024')).toBe(false);
    });
  });
});
