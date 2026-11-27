import { describe, it, expect } from 'vitest';
import { createIntl } from 'react-intl';
import {
  buildRangeText,
  isOutOfRange,
} from '@/components/PropertiesPanel/CustomPanels/shared/rangeValidation';

const intl = createIntl({ locale: 'en' });

describe('isOutOfRange', () => {
  it('flags values below min and above max', () => {
    expect(isOutOfRange(4, 5, 10)).toBe(true);
    expect(isOutOfRange(11, 5, 10)).toBe(true);
  });

  it('accepts boundaries and inner values', () => {
    expect(isOutOfRange(5, 5, 10)).toBe(false);
    expect(isOutOfRange(10, 5, 10)).toBe(false);
    expect(isOutOfRange('7', 5, 10)).toBe(false);
  });

  it('ignores empty and non-numeric values', () => {
    expect(isOutOfRange('', 5, 10)).toBe(false);
    expect(isOutOfRange('abc', 5, 10)).toBe(false);
  });

  it('supports a single bound', () => {
    expect(isOutOfRange(1, 5)).toBe(true);
    expect(isOutOfRange(100, undefined, 10)).toBe(true);
  });
});

describe('buildRangeText', () => {
  it('formats a full range', () => {
    expect(buildRangeText(intl, 500, 5000)).toBe('Range allowed: 500–5000');
  });

  it('formats single bounds', () => {
    expect(buildRangeText(intl, 5)).toBe('Minimum value allowed: 5');
    expect(buildRangeText(intl, undefined, 9)).toBe('Maximum value allowed: 9');
  });

  it('returns undefined with no bounds', () => {
    expect(buildRangeText(intl)).toBeUndefined();
  });
});
