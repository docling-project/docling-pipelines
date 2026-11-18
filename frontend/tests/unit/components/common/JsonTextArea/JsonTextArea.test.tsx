import { describe, it, expect, vi } from 'vitest';
import { screen, fireEvent } from '@testing-library/react';
import { renderWithProviders } from '../../../../utils/renderWithProviders';
import { JsonTextArea } from '@/components/common/JsonTextArea/JsonTextArea';

describe('JsonTextArea', () => {
  it('renders a textarea with the given id', () => {
    renderWithProviders(<JsonTextArea id="my-json" labelText="Config" storedValue={null} onChange={vi.fn()} />);
    expect(document.getElementById('my-json')).not.toBeNull();
  });

  it('shows serialized storedValue when no raw edit is in progress', () => {
    renderWithProviders(
      <JsonTextArea
        id="cfg"
        labelText="Config"
        storedValue={{ key: 'val' }}
        onChange={vi.fn()}
      />
    );
    const ta = document.getElementById('cfg') as HTMLTextAreaElement;
    expect(ta.value).toContain('"key"');
    expect(ta.value).toContain('"val"');
  });

  it('is empty when storedValue is null', () => {
    renderWithProviders(<JsonTextArea id="cfg" labelText="Config" storedValue={null} onChange={vi.fn()} />);
    const ta = document.getElementById('cfg') as HTMLTextAreaElement;
    expect(ta.value).toBe('');
  });

  it('calls onChange with parsed object for valid JSON input', () => {
    const onChange = vi.fn();
    renderWithProviders(<JsonTextArea id="cfg" labelText="Config" storedValue={null} onChange={onChange} />);
    const ta = document.getElementById('cfg') as HTMLTextAreaElement;
    fireEvent.change(ta, { target: { value: '{"a":1}' } });
    expect(onChange).toHaveBeenCalledWith({ a: 1 });
  });

  it('calls onChange with null for empty input', () => {
    const onChange = vi.fn();
    renderWithProviders(<JsonTextArea id="cfg" labelText="Config" storedValue={{ a: 1 }} onChange={onChange} />);
    const ta = document.getElementById('cfg') as HTMLTextAreaElement;
    fireEvent.change(ta, { target: { value: '' } });
    expect(onChange).toHaveBeenCalledWith(null);
  });

  it('does not call onChange for invalid JSON', () => {
    const onChange = vi.fn();
    renderWithProviders(<JsonTextArea id="cfg" labelText="Config" storedValue={null} onChange={onChange} />);
    const ta = document.getElementById('cfg') as HTMLTextAreaElement;
    fireEvent.change(ta, { target: { value: 'not-json' } });
    expect(onChange).not.toHaveBeenCalled();
  });

  it('shows error message after blur with invalid JSON', () => {
    renderWithProviders(<JsonTextArea id="cfg" labelText="Config" storedValue={null} onChange={vi.fn()} />);
    const ta = document.getElementById('cfg') as HTMLTextAreaElement;
    fireEvent.change(ta, { target: { value: 'invalid' } });
    fireEvent.blur(ta);
    expect(screen.getByText('Must be a valid JSON object.')).toBeInTheDocument();
  });

  it('renders external invalid text when invalid prop is provided', () => {
    renderWithProviders(
      <JsonTextArea
        id="cfg"
        labelText="Config"
        storedValue={null}
        onChange={vi.fn()}
        invalid
        invalidText="Custom error message"
      />
    );
    expect(screen.getByText('Custom error message')).toBeInTheDocument();
  });

  it('applies placeholder when provided', () => {
    renderWithProviders(
      <JsonTextArea
        id="cfg"
        labelText="Config"
        storedValue={null}
        onChange={vi.fn()}
        placeholder='{"key": "value"}'
      />
    );
    const ta = document.getElementById('cfg') as HTMLTextAreaElement;
    expect(ta.placeholder).toBe('{"key": "value"}');
  });
});
