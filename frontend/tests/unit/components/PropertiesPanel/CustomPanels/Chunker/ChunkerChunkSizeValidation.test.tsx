import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, fireEvent, within } from '@testing-library/react';
import { renderWithProviders } from '../../../../../utils/renderWithProviders';
import { ChunkerPanelBody } from '@/components/PropertiesPanel/CustomPanels/Chunker/Chunker';
import { shouldDisableSave } from '@/components/PropertiesPanel/saveValidation';

const SIMPLE_RANGE_TEXT = 'Range allowed: 500–5000';
const HYBRID_RANGE_TEXT = 'Range allowed: 100–2048';

/**
 * Minimal stateful stand-in for Elyra's properties controller. Every property
 * update re-evaluates Save gating (like Elyra's propertyListener) and re-renders.
 */
function setup(initial: Record<string, unknown>) {
  const values: Record<string, unknown> = { ...initial };
  const setSaveButtonDisable = vi.fn();
  const controller = {
    getAppData: vi.fn(() => ({ operatorMetadata: {} })),
    getPropertyValue: vi.fn(({ name }: { name: string }) => values[name]),
    getPropertyValues: vi.fn(() => ({ ...values })),
    updatePropertyValue: vi.fn(({ name }: { name: string }, value: unknown) => {
      values[name] = value;
      setSaveButtonDisable(shouldDisableSave('chunker', {}, { ...values }));
    }),
    setSaveButtonDisable,
  };
  const utils = renderWithProviders(<ChunkerPanelBody controller={controller} />);
  const rerender = (): void => utils.rerender(<ChunkerPanelBody controller={controller} />);
  const sizeInput = (): HTMLInputElement =>
    document.getElementById('chunker-chunk-size') as HTMLInputElement;
  const typeSize = (value: string): void => {
    fireEvent.change(sizeInput(), { target: { value } });
    rerender();
  };
  const selectChunkType = (label: string): void => {
    const dropdown = document.getElementById('chunker-chunk-type') as HTMLElement;
    fireEvent.click(within(dropdown.closest('.cds--dropdown') as HTMLElement).getByRole('combobox'));
    fireEvent.click(screen.getByRole('option', { name: label }));
    rerender();
  };
  const lastSaveDisabled = (): boolean | undefined => setSaveButtonDisable.mock.calls.at(-1)?.[0];
  return { controller, typeSize, selectChunkType, sizeInput, lastSaveDisabled };
}

describe('Chunker chunk size range validation', () => {
  beforeEach(() => {
    // jsdom does not implement scrollIntoView; Carbon Dropdown calls it when opening.
    Element.prototype.scrollIntoView = vi.fn();
  });

  describe('simple (500-5000 characters)', () => {
    it('shows an inline message and disables Save below the minimum', () => {
      const t = setup({ chunk_type: 'simple', chunk_size: 1000 });
      t.typeSize('499');
      expect(screen.getByText(SIMPLE_RANGE_TEXT)).toBeInTheDocument();
      expect(t.sizeInput()).toHaveAttribute('aria-invalid', 'true');
      expect(t.lastSaveDisabled()).toBe(true);
    });

    it('shows an inline message and disables Save above the maximum', () => {
      const t = setup({ chunk_type: 'simple', chunk_size: 1000 });
      t.typeSize('5001');
      expect(screen.getByText(SIMPLE_RANGE_TEXT)).toBeInTheDocument();
      expect(t.lastSaveDisabled()).toBe(true);
    });

    it.each(['500', '5000'])('accepts the boundary value %s', (value) => {
      const t = setup({ chunk_type: 'simple', chunk_size: 1000 });
      t.typeSize(value);
      expect(screen.queryByText(SIMPLE_RANGE_TEXT)).not.toBeInTheDocument();
      expect(t.sizeInput()).not.toHaveAttribute('aria-invalid', 'true');
      expect(t.lastSaveDisabled()).toBe(false);
    });

    it('flags zero and negative values instead of ignoring them', () => {
      const t = setup({ chunk_type: 'simple', chunk_size: 1000 });
      t.typeSize('0');
      expect(t.controller.updatePropertyValue).toHaveBeenCalledWith({ name: 'chunk_size' }, 0);
      expect(screen.getByText(SIMPLE_RANGE_TEXT)).toBeInTheDocument();
      expect(t.lastSaveDisabled()).toBe(true);
    });

    it('clears the error and re-enables Save once a valid value is entered', () => {
      const t = setup({ chunk_type: 'simple', chunk_size: 1000 });
      t.typeSize('100');
      expect(screen.getByText(SIMPLE_RANGE_TEXT)).toBeInTheDocument();
      expect(t.lastSaveDisabled()).toBe(true);

      t.typeSize('1200');
      expect(screen.queryByText(SIMPLE_RANGE_TEXT)).not.toBeInTheDocument();
      expect(t.lastSaveDisabled()).toBe(false);
    });

    it('shows no message for a valid stored value', () => {
      setup({ chunk_type: 'simple', chunk_size: 1000 });
      expect(screen.queryByText(SIMPLE_RANGE_TEXT)).not.toBeInTheDocument();
    });
  });

  describe('hybrid (100-2048 tokens)', () => {
    it('shows an inline message below the minimum', () => {
      const t = setup({ chunk_type: 'hybrid', chunk_size: 512 });
      t.typeSize('99');
      expect(screen.getByText(HYBRID_RANGE_TEXT)).toBeInTheDocument();
      expect(t.lastSaveDisabled()).toBe(true);
    });

    it('shows an inline message above the maximum', () => {
      const t = setup({ chunk_type: 'hybrid', chunk_size: 512 });
      t.typeSize('2049');
      expect(screen.getByText(HYBRID_RANGE_TEXT)).toBeInTheDocument();
      expect(t.lastSaveDisabled()).toBe(true);
    });

    it.each(['100', '2048'])('accepts the boundary value %s', (value) => {
      const t = setup({ chunk_type: 'hybrid', chunk_size: 512 });
      t.typeSize(value);
      expect(screen.queryByText(HYBRID_RANGE_TEXT)).not.toBeInTheDocument();
      expect(t.lastSaveDisabled()).toBe(false);
    });
  });

  describe('switching chunk type', () => {
    it('revalidates a value that is valid for Simple but not Hybrid, and back', () => {
      const t = setup({ chunk_type: 'simple', chunk_size: 3000 });
      expect(screen.queryByText(HYBRID_RANGE_TEXT)).not.toBeInTheDocument();

      t.selectChunkType('Hybrid (Docling)');
      expect(t.controller.updatePropertyValue).toHaveBeenCalledWith({ name: 'chunk_type' }, 'hybrid');
      expect(screen.getByText(HYBRID_RANGE_TEXT)).toBeInTheDocument();
      expect(t.lastSaveDisabled()).toBe(true);

      t.selectChunkType('Simple');
      expect(screen.queryByText(HYBRID_RANGE_TEXT)).not.toBeInTheDocument();
      expect(screen.queryByText(SIMPLE_RANGE_TEXT)).not.toBeInTheDocument();
      expect(t.lastSaveDisabled()).toBe(false);
    });

    it('revalidates a value that is valid for Hybrid but not Simple', () => {
      const t = setup({ chunk_type: 'hybrid', chunk_size: 300 });
      expect(screen.queryByText(SIMPLE_RANGE_TEXT)).not.toBeInTheDocument();

      t.selectChunkType('Simple');
      expect(screen.getByText(SIMPLE_RANGE_TEXT)).toBeInTheDocument();
      expect(t.lastSaveDisabled()).toBe(true);
    });

    it('does not validate chunk size for Semantic', () => {
      const t = setup({ chunk_type: 'simple', chunk_size: 100 });
      expect(screen.getByText(SIMPLE_RANGE_TEXT)).toBeInTheDocument();

      t.selectChunkType('Semantic');
      expect(document.getElementById('chunker-chunk-size')).toBeNull();
      expect(screen.queryByText(SIMPLE_RANGE_TEXT)).not.toBeInTheDocument();
      expect(t.lastSaveDisabled()).toBe(false);
    });
  });
});
