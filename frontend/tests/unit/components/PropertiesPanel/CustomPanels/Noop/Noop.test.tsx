import { describe, it, expect, vi } from 'vitest';
import { renderWithProviders } from '../../../../../utils/renderWithProviders';
import { screen, fireEvent } from '@testing-library/react';
import React from 'react';
import { NoopPanelBody } from '@/components/PropertiesPanel/CustomPanels/Noop/Noop';

function makeController(overrides: Record<string, unknown> = {}) {
  return {
    getPropertyValue: vi.fn(),
    updatePropertyValue: vi.fn(),
    getAppData: vi.fn().mockReturnValue({ operatorMetadata: {} }),
    setSaveButtonDisable: vi.fn(),
    ...overrides,
  };
}

describe('NoopPanelBody', () => {
  it('renders the sleep duration field', () => {
    const controller = makeController();
    renderWithProviders(<NoopPanelBody controller={controller} />);
    // Label text appears multiple times (tooltip button + label span) — use getAllByText
    const labels = screen.getAllByText('Sleep duration (seconds)');
    expect(labels.length).toBeGreaterThan(0);
  });

  it('uses default value (0) when controller returns undefined', () => {
    const controller = makeController({
      getPropertyValue: vi.fn().mockReturnValue(undefined),
    });
    renderWithProviders(<NoopPanelBody controller={controller} />);
    const input = document.querySelector('input#sleep_sec') as HTMLInputElement;
    expect(input).toBeTruthy();
    expect(Number(input.value)).toBe(0);
  });

  it('reads persisted value from controller', () => {
    const controller = makeController({
      getPropertyValue: vi.fn().mockReturnValue(5),
    });
    renderWithProviders(<NoopPanelBody controller={controller} />);
    const input = document.querySelector('input#sleep_sec') as HTMLInputElement;
    expect(Number(input.value)).toBe(5);
  });

  it('number input is present and interactive', () => {
    const controller = makeController();
    renderWithProviders(<NoopPanelBody controller={controller} />);
    const input = document.querySelector('input#sleep_sec') as HTMLInputElement;
    expect(input).toBeTruthy();
    fireEvent.change(input, { target: { value: '3' } });
    expect(input).toBeTruthy(); // still mounted after change
  });

  it('uses operator metadata default when available', () => {
    const controller = makeController({
      getPropertyValue: vi.fn().mockReturnValue(undefined),
      getAppData: vi.fn().mockReturnValue({
        operatorMetadata: {
          noop: {
            attributes: {
              sleep_sec: { default: 10, required: false },
            },
          },
        },
      }),
    });
    renderWithProviders(<NoopPanelBody controller={controller} />);
    const input = document.querySelector('input#sleep_sec') as HTMLInputElement;
    expect(Number(input.value)).toBe(10);
  });
});
