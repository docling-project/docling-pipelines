/**
 * @file JsonTextArea — controlled textarea for JSON object input.
 *
 * Behaviour of component:
 * - Displays the user's in-progress raw text at all times (never clears mid-edit)
 * - Persists a parsed object the moment the input becomes valid JSON
 * - Persists null when the input is cleared to empty string
 * - Never persists an invalid JSON string
 * - Shows an inline error only after the field has been touched (on blur)
 * - Accepts optional `invalid`/`invalidText` props for external validation
 */

import React, { useState } from 'react';
import { TextArea } from '@carbon/react';
import { useIntl } from 'react-intl';
import { isValidJsonObject, toJsonString } from '@/utils/json';
import { messages } from './JsonTextArea.messages';

interface JsonTextAreaProps {
  /** Carbon TextArea `id` — must be unique on the page */
  id: string;
  /** Visible label (used for accessibility even when hidden) */
  labelText: string;
  /** Current persisted value from the controller (object or null/undefined) */
  storedValue: Record<string, unknown> | null | undefined;
  /** Called with a parsed object on valid input, or null on empty */
  onChange: (value: Record<string, unknown> | null) => void;
  /** Placeholder text shown when the field is empty */
  placeholder?: string;
  /** Number of visible rows */
  rows?: number;
  /** External invalid state */
  invalid?: boolean;
  /** Error message shown when `invalid` is true */
  invalidText?: string;
}

export function JsonTextArea({
  id,
  labelText,
  storedValue,
  onChange,
  placeholder,
  rows = 4,
  invalid: externalInvalid,
  invalidText: externalInvalidText,
}: JsonTextAreaProps): React.JSX.Element {
  const intl = useIntl();
  // The raw string the user is currently typing.
  // null means display the serialised storedValue instead.
  const [rawEdit, setRawEdit] = useState<string | null>(null);
  const [touched, setTouched] = useState(false);

  // Value shown in the textarea: in-progress text > serialised stored value > ''
  const displayValue = rawEdit ?? toJsonString(storedValue);

  const internalInvalid = touched && displayValue !== '' && !isValidJsonObject(displayValue);
  const showError = (externalInvalid ?? false) || internalInvalid;
  const errorMessage = externalInvalid
    ? (externalInvalidText ?? '')
    : intl.formatMessage(messages.invalidJson);

  const handleChange = (e: React.ChangeEvent<HTMLTextAreaElement>): void => {
    const raw = e.target.value;
    setRawEdit(raw);

    if (raw === '') {
      onChange(null);
      return;
    }

    try {
      const parsed = JSON.parse(raw) as unknown;
      if (typeof parsed === 'object' && parsed !== null && !Array.isArray(parsed)) {
        onChange(parsed as Record<string, unknown>);
      }
      // Invalid shape (array, primitive). Don't persist, keep raw in state
    } catch {
      // Invalid JSON. Don't persist, keep raw in state
    }
  };

  const handleBlur = (): void => {
    setTouched(true);
    // If the current text is valid, clear rawEdit so display reverts to storedValue
    if (rawEdit !== null && isValidJsonObject(rawEdit)) {
      setRawEdit(null);
    }
  };

  return (
    <TextArea
      id={id}
      labelText={labelText}
      hideLabel
      placeholder={placeholder}
      value={displayValue}
      rows={rows}
      invalid={showError}
      invalidText={errorMessage}
      onChange={handleChange}
      onBlur={handleBlur}
    />
  );
}
