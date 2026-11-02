import { describe, it, expect, vi } from 'vitest';
import { screen, fireEvent } from '@testing-library/react';
import { renderWithProviders } from '../../../../utils/renderWithProviders';
import React from 'react';
import { VaultInput, type VaultInputProps } from '@/components/common/VaultInput/VaultInput';

function renderVaultInput(props: Partial<VaultInputProps> = {}) {
  const defaults: VaultInputProps = {
    id: 'test-vault-input',
    labelText: 'API Key',
    value: '',
    onChange: vi.fn(),
    ...props,
  };
  return { ...renderWithProviders(React.createElement(VaultInput, defaults)), ...defaults };
}

describe('VaultInput', () => {
  it('plain value → password input is rendered (not vault mode)', () => {
    renderVaultInput({ value: 'plain-value' });
    const input = document.querySelector('input[type="password"]') ?? document.querySelector('input[type="text"]');
    expect(input).toBeTruthy();
    expect((input as HTMLInputElement).value).toBe('plain-value');
  });

  it('renders labelText in header when hideLabel is false and custom labelComponent when provided', () => {
    const { rerender } = renderVaultInput({ labelText: 'Custom Label' });
    const labelSpan = document.querySelector('span[class*="label"]');
    expect(labelSpan?.textContent).toBe('Custom Label');

    rerender(
      <VaultInput
        id="test-vault-input"
        labelText="Custom Label"
        value=""
        onChange={vi.fn()}
        labelComponent={<span data-testid="custom-label-comp">Custom Comp</span>}
      />
    );
    expect(screen.getByTestId('custom-label-comp')).toBeDefined();
  });

  it('hides header label when hideLabel is true and no labelComponent is provided', () => {
    renderVaultInput({ labelText: 'Secret Label', hideLabel: true });
    const labelSpan = document.querySelector('span[class*="label"]');
    expect(labelSpan).toBeNull();
  });

  it('multiline direct input renders TextArea', () => {
    const onChange = vi.fn();
    renderVaultInput({ multiline: true, value: 'line1\nline2', onChange, rows: 5 });
    const textarea = document.querySelector('textarea');
    expect(textarea).toBeTruthy();
    expect(textarea?.value).toBe('line1\nline2');
    expect(textarea?.getAttribute('rows')).toBe('5');

    fireEvent.change(textarea!, { target: { value: 'updated multiline' } });
    expect(onChange).toHaveBeenCalledWith('updated multiline');
  });

  it('handles plain text password input change', () => {
    const onChange = vi.fn();
    renderVaultInput({ value: 'init', onChange });
    const input = document.querySelector('input[type="password"]') as HTMLInputElement;
    fireEvent.change(input, { target: { value: 'new-plain' } });
    expect(onChange).toHaveBeenCalledWith('new-plain');
  });

  it('vault:// value → vault:// tag indicator shown and renders text input with stripped prefix', () => {
    renderVaultInput({ value: 'vault://hashicorp/docpipe/opensearch#password' });
    const elements = screen.getAllByText('vault://');
    expect(elements.length).toBeGreaterThan(0);

    const input = document.querySelector('input[id="test-vault-input"]') as HTMLInputElement;
    expect(input.value).toBe('hashicorp/docpipe/opensearch#password');
  });

  it('editing suffix in vault mode calls onChange with prepended vault://', () => {
    const onChange = vi.fn();
    renderVaultInput({ value: 'vault://secret/path', onChange });
    const input = document.querySelector('input[id="test-vault-input"]') as HTMLInputElement;
    fireEvent.change(input, { target: { value: 'new/secret/path#token' } });
    expect(onChange).toHaveBeenCalledWith('vault://new/secret/path#token');
  });

  it('flags empty vault suffix as invalid vault uri', () => {
    renderVaultInput({ value: 'vault://' });
    expect(screen.getByText(/Enter the vault path, e.g. hashicorp\/docpipe\/opensearch#password/i)).toBeDefined();
  });

  it('shows custom invalidText when invalid is true and not vault uri error', () => {
    renderVaultInput({ value: 'plain', invalid: true, invalidText: 'Field is required' });
    expect(screen.getByText('Field is required')).toBeDefined();
  });

  it('toggling vault mode from plain to vault restores vault value and calls onChange', () => {
    const onChange = vi.fn();
    renderVaultInput({ value: 'my-direct-pass', onChange });
    const toggle = document.querySelector('[id="test-vault-input-vault-toggle"]') as HTMLElement;
    fireEvent.click(toggle);
    expect(onChange).toHaveBeenCalledWith('vault://');
  });

  it('toggling vault mode off restores last direct value or defaultValue', () => {
    const onChange = vi.fn();
    const { rerender } = renderVaultInput({
      value: 'plain-secret',
      defaultValue: 'default-secret',
      onChange,
    });

    // Toggle on
    const toggle = document.querySelector('[id="test-vault-input-vault-toggle"]') as HTMLElement;
    fireEvent.click(toggle);
    expect(onChange).toHaveBeenCalledWith('vault://');

    // Simulate parent updating value prop to vault URI
    rerender(
      <VaultInput
        id="test-vault-input"
        labelText="API Key"
        value="vault://my/secret#key"
        defaultValue="default-secret"
        onChange={onChange}
      />
    );

    // Toggle off
    fireEvent.click(toggle);
    expect(onChange).toHaveBeenCalledWith('plain-secret');
  });

  it('toggling vault mode off when lastDirectValue is empty uses defaultValue or empty string', () => {
    const onChange = vi.fn();
    renderVaultInput({
      value: 'vault://init/path',
      defaultValue: 'fallback-default',
      onChange,
    });
    const toggle = document.querySelector('[id="test-vault-input-vault-toggle"]') as HTMLElement;
    fireEvent.click(toggle);
    expect(onChange).toHaveBeenCalledWith('fallback-default');
  });

  it('syncs state when external value prop changes from plain to vault and back', () => {
    const { rerender } = renderVaultInput({ value: 'initial-plain' });
    expect(document.querySelector('input[type="password"]')).toBeTruthy();

    // Change to vault
    rerender(
      <VaultInput
        id="test-vault-input"
        labelText="API Key"
        value="vault://new/path#key"
        onChange={vi.fn()}
      />
    );
    expect(screen.getAllByText('vault://').length).toBeGreaterThan(0);
    const textInput = document.querySelector('input[id="test-vault-input"]') as HTMLInputElement;
    expect(textInput.value).toBe('new/path#key');

    // Change back to plain
    rerender(
      <VaultInput
        id="test-vault-input"
        labelText="API Key"
        value="updated-plain"
        onChange={vi.fn()}
      />
    );
    expect(document.querySelector('input[type="password"]')).toBeTruthy();
  });

  it('password visibility toggle in PasswordInput can be toggled', () => {
    renderVaultInput({ value: 'my-secret' });
    const pwInput = document.querySelector('input[id="test-vault-input"]') as HTMLInputElement;
    expect(pwInput.type).toBe('password');
    const visibilityBtn = document.querySelector('button[class*="cds--password-input-toggle"]') as HTMLButtonElement;
    if (visibilityBtn) {
      fireEvent.click(visibilityBtn);
      expect(pwInput.type).toBe('text');
    }
  });

  it('toggling vault mode off when current value is not vault reference saves direct value', () => {
    const onChange = vi.fn();
    renderVaultInput({ value: 'plain-text', onChange });
    const toggle = document.querySelector('[id="test-vault-input-vault-toggle"]') as HTMLElement;
    // Toggle on
    fireEvent.click(toggle);
    expect(onChange).toHaveBeenCalledWith('vault://');
    // Toggle off without value being updated to vault://
    fireEvent.click(toggle);
    expect(onChange).toHaveBeenCalledWith('plain-text');
  });

  it('disabled prop disables inputs and toggle', () => {
    renderVaultInput({ value: '', disabled: true });
    const inputs = document.querySelectorAll('input');
    inputs.forEach((input) => {
      if (!input.closest('[role="status"]')) {
        expect(input.disabled === true || input.type === 'checkbox').toBeTruthy();
      }
    });
  });

  it('empty and undefined value defaults are handled gracefully', () => {
    // @ts-expect-error testing undefined value prop
    renderVaultInput({ value: undefined });
    const input = document.querySelector('input');
    expect(input).toBeTruthy();
  });
});
