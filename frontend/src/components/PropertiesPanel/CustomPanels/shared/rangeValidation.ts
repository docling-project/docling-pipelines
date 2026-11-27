/**
 * @file Numeric range helpers shared by operator panels.
 *
 * Extracted from ProviderFieldsForm so that other panels (e.g. Chunker) can show
 * the same localized range message and apply the same out-of-range rule.
 */

import type { IntlShape } from 'react-intl';
import { messages } from './ProviderFieldsForm.messages';

export function buildRangeText(intl: IntlShape, minValue?: number, maxValue?: number): string | undefined {
  if (minValue !== undefined && maxValue !== undefined) {
    return intl.formatMessage(messages.rangeAllowed, { min: minValue, max: maxValue });
  }
  if (minValue !== undefined) {return intl.formatMessage(messages.minimumAllowed, { min: minValue });}
  if (maxValue !== undefined) {return intl.formatMessage(messages.maximumAllowed, { max: maxValue });}
  return undefined;
}

export function isOutOfRange(value: number | string, minValue?: number, maxValue?: number): boolean {
  if (value === '') {return false;}
  const n = Number(value);
  if (!Number.isFinite(n)) {return false;}
  if (minValue !== undefined && n < minValue) {return true;}
  if (maxValue !== undefined && n > maxValue) {return true;}
  return false;
}
