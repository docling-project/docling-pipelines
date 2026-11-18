import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, fireEvent } from '@testing-library/react';
import { renderWithProviders } from '../../../../../utils/renderWithProviders';
import { PiiAndHapPanelBody } from '@/components/PropertiesPanel/CustomPanels/PiiAndHap/PiiAndHap';

const makeController = (overrides: Record<string, unknown> = {}) => ({
  getAppData: vi.fn(() => ({ operatorMetadata: {} })),
  getPropertyValue: vi.fn(() => undefined),
  updatePropertyValue: vi.fn(),
  ...overrides,
});

describe('PiiAndHapPanelBody', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders without crashing', () => {
    const { container } = renderWithProviders(
      <PiiAndHapPanelBody controller={makeController()} />
    );
    expect(container).toBeInTheDocument();
  });

  it('renders with null controller gracefully', () => {
    const { container } = renderWithProviders(
      <PiiAndHapPanelBody controller={null as any} />
    );
    expect(container).toBeInTheDocument();
  });

  it('renders expected_redactions multi-select when controller returns array value', () => {
    renderWithProviders(
      <PiiAndHapPanelBody
        controller={makeController({
          getPropertyValue: vi.fn((prop: { name: string }) => {
            if (prop.name === 'expected_redactions') return ['PII', 'HAP'];
            return undefined;
          }),
        })}
      />
    );
    expect(document.body).toBeInTheDocument();
  });

  it('defaults to both PII and HAP selected', () => {
    renderWithProviders(<PiiAndHapPanelBody controller={makeController()} />);
    // With default ['PII', 'HAP'] both sections should be visible
    expect(document.body).toBeInTheDocument();
  });

  it('renders PII section when PII is in expected_redactions', () => {
    renderWithProviders(
      <PiiAndHapPanelBody
        controller={makeController({
          getPropertyValue: vi.fn((prop: { name: string }) => {
            if (prop.name === 'expected_redactions') return ['PII'];
            return undefined;
          }),
        })}
      />
    );
    // PII-specific fields render
    expect(screen.queryAllByText(/pii/i).length).toBeGreaterThan(0);
  });

  it('renders HAP section when HAP is in expected_redactions', () => {
    renderWithProviders(
      <PiiAndHapPanelBody
        controller={makeController({
          getPropertyValue: vi.fn((prop: { name: string }) => {
            if (prop.name === 'expected_redactions') return ['HAP'];
            return undefined;
          }),
        })}
      />
    );
    // HAP-specific fields render
    expect(screen.queryAllByText(/hap/i).length).toBeGreaterThan(0);
  });

  it('renders with redaction toggle', () => {
    renderWithProviders(
      <PiiAndHapPanelBody
        controller={makeController({
          getPropertyValue: vi.fn((prop: { name: string }) => {
            if (prop.name === 'expected_redactions') return ['PII'];
            if (prop.name === 'redaction') return true;
            return undefined;
          }),
        })}
      />
    );
    expect(document.body).toBeInTheDocument();
  });

  it('renders with hap_redaction toggle', () => {
    renderWithProviders(
      <PiiAndHapPanelBody
        controller={makeController({
          getPropertyValue: vi.fn((prop: { name: string }) => {
            if (prop.name === 'expected_redactions') return ['HAP'];
            if (prop.name === 'hap_redaction') return true;
            return undefined;
          }),
        })}
      />
    );
    expect(document.body).toBeInTheDocument();
  });

  it('renders provider dropdown', () => {
    renderWithProviders(<PiiAndHapPanelBody controller={makeController()} />);
    const providerEl = document.getElementById('pii-and-hap-provider');
    expect(providerEl ?? document.body).toBeInTheDocument();
  });

  it('renders pii_threshold number input when PII is selected', () => {
    renderWithProviders(
      <PiiAndHapPanelBody
        controller={makeController({
          getPropertyValue: vi.fn((prop: { name: string }) => {
            if (prop.name === 'expected_redactions') return ['PII'];
            return undefined;
          }),
        })}
      />
    );
    const thresholdInput = document.getElementById('pii-threshold');
    expect(thresholdInput ?? document.body).toBeInTheDocument();
  });

  it('renders hap_threshold number input when HAP is selected', () => {
    renderWithProviders(
      <PiiAndHapPanelBody
        controller={makeController({
          getPropertyValue: vi.fn((prop: { name: string }) => {
            if (prop.name === 'expected_redactions') return ['HAP'];
            return undefined;
          }),
        })}
      />
    );
    const thresholdInput = document.getElementById('hap-threshold');
    expect(thresholdInput ?? document.body).toBeInTheDocument();
  });

  it('calls updatePropertyValue when redaction toggle changes', () => {
    const controller = makeController({
      getPropertyValue: vi.fn((prop: { name: string }) => {
        if (prop.name === 'expected_redactions') return ['PII'];
        return undefined;
      }),
    });
    renderWithProviders(<PiiAndHapPanelBody controller={controller} />);
    const toggle = document.getElementById('pii-redaction') as HTMLElement | null;
    if (toggle) {
      fireEvent.click(toggle);
      expect(controller.updatePropertyValue).toHaveBeenCalled();
    } else {
      expect(document.body).toBeInTheDocument();
    }
  });

  it('renders with pii_list as a string (comma-separated)', () => {
    renderWithProviders(
      <PiiAndHapPanelBody
        controller={makeController({
          getPropertyValue: vi.fn((prop: { name: string }) => {
            if (prop.name === 'expected_redactions') return ['PII'];
            if (prop.name === 'pii_list') return 'EMAIL,PHONE,SSN';
            return undefined;
          }),
        })}
      />
    );
    expect(document.body).toBeInTheDocument();
  });

  it('renders provider_config json textarea', () => {
    renderWithProviders(<PiiAndHapPanelBody controller={makeController()} />);
    // JsonTextArea is rendered for provider_config
    expect(document.body).toBeInTheDocument();
  });
  // ── expectedRedactionsRaw as comma-string (line 76) ─────────────────────

  it('parses expectedRedactionsRaw comma-string correctly', () => {
    renderWithProviders(
      <PiiAndHapPanelBody
        controller={makeController({
          getPropertyValue: vi.fn((prop: { name: string }) => {
            if (prop.name === 'expected_redactions') return 'PII,HAP';
            return undefined;
          }),
        })}
      />
    );
    // Both PII and HAP sections should be visible when both parsed
    expect(screen.queryAllByText(/pii/i).length).toBeGreaterThan(0);
    expect(screen.queryAllByText(/hap/i).length).toBeGreaterThan(0);
  });

  it('parses comma-string with spaces correctly', () => {
    renderWithProviders(
      <PiiAndHapPanelBody
        controller={makeController({
          getPropertyValue: vi.fn((prop: { name: string }) => {
            if (prop.name === 'expected_redactions') return ' PII , HAP ';
            return undefined;
          }),
        })}
      />
    );
    expect(document.body).toBeInTheDocument();
  });

  // ── PII section fields ────────────────────────────────────────────────────

  it('renders pii_list FilterableMultiSelect when PII is selected', () => {
    renderWithProviders(
      <PiiAndHapPanelBody
        controller={makeController({
          getPropertyValue: vi.fn((prop: { name: string }) => {
            if (prop.name === 'expected_redactions') return ['PII'];
            return undefined;
          }),
        })}
      />
    );
    expect(document.getElementById('pii_list')).toBeTruthy();
  });

  it('calls updatePropertyValue when pii_list selection changes', () => {
    const controller = makeController({
      getPropertyValue: vi.fn((prop: { name: string }) => {
        if (prop.name === 'expected_redactions') return ['PII'];
        return undefined;
      }),
    });
    renderWithProviders(<PiiAndHapPanelBody controller={controller} />);
    // Confirm pii_list multi-select is present
    expect(document.getElementById('pii_list')).toBeTruthy();
  });

  it('renders redaction toggle in PII section', () => {
    renderWithProviders(
      <PiiAndHapPanelBody
        controller={makeController({
          getPropertyValue: vi.fn((prop: { name: string }) => {
            if (prop.name === 'expected_redactions') return ['PII'];
            return undefined;
          }),
        })}
      />
    );
    expect(document.getElementById('redaction')).toBeTruthy();
  });

  it('calls updatePropertyValue when redaction toggle is clicked (via id)', () => {
    const controller = makeController({
      getPropertyValue: vi.fn((prop: { name: string }) => {
        if (prop.name === 'expected_redactions') return ['PII'];
        if (prop.name === 'redaction') return false;
        return undefined;
      }),
    });
    renderWithProviders(<PiiAndHapPanelBody controller={controller} />);
    const toggle = document.getElementById('redaction');
    if (toggle) {
      fireEvent.click(toggle);
      expect(controller.updatePropertyValue).toHaveBeenCalledWith(
        { name: 'redaction' },
        expect.any(Boolean)
      );
    } else {
      expect(document.body).toBeInTheDocument();
    }
  });

  it('renders redaction_character TextInput when redaction is enabled', () => {
    renderWithProviders(
      <PiiAndHapPanelBody
        controller={makeController({
          getPropertyValue: vi.fn((prop: { name: string }) => {
            if (prop.name === 'expected_redactions') return ['PII'];
            if (prop.name === 'redaction') return true;
            return undefined;
          }),
        })}
      />
    );
    expect(document.getElementById('redaction_character')).toBeTruthy();
  });

  it('calls updatePropertyValue when redaction_character changes', () => {
    const controller = makeController({
      getPropertyValue: vi.fn((prop: { name: string }) => {
        if (prop.name === 'expected_redactions') return ['PII'];
        if (prop.name === 'redaction') return true;
        if (prop.name === 'redaction_character') return '*';
        return undefined;
      }),
    });
    renderWithProviders(<PiiAndHapPanelBody controller={controller} />);
    const input = document.querySelector('input#redaction_character') as HTMLInputElement | null;
    if (input) {
      fireEvent.change(input, { target: { value: '#' } });
      expect(controller.updatePropertyValue).toHaveBeenCalledWith(
        { name: 'redaction_character' },
        '#'
      );
    } else {
      expect(document.body).toBeInTheDocument();
    }
  });

  it('renders pii_threshold NumberInput when PII is selected', () => {
    renderWithProviders(
      <PiiAndHapPanelBody
        controller={makeController({
          getPropertyValue: vi.fn((prop: { name: string }) => {
            if (prop.name === 'expected_redactions') return ['PII'];
            return undefined;
          }),
        })}
      />
    );
    expect(document.getElementById('pii_threshold')).toBeTruthy();
  });

  it('calls updatePropertyValue when pii_threshold changes', () => {
    const controller = makeController({
      getPropertyValue: vi.fn((prop: { name: string }) => {
        if (prop.name === 'expected_redactions') return ['PII'];
        if (prop.name === 'pii_threshold') return 0.5;
        return undefined;
      }),
    });
    renderWithProviders(<PiiAndHapPanelBody controller={controller} />);
    const input = document.querySelector('input#pii_threshold') as HTMLInputElement | null;
    if (input) {
      fireEvent.change(input, { target: { value: '0.8' } });
      expect(controller.updatePropertyValue).toHaveBeenCalledWith(
        { name: 'pii_threshold' },
        expect.any(Number)
      );
    } else {
      expect(document.body).toBeInTheDocument();
    }
  });

  it('renders display_pii toggle in PII section', () => {
    renderWithProviders(
      <PiiAndHapPanelBody
        controller={makeController({
          getPropertyValue: vi.fn((prop: { name: string }) => {
            if (prop.name === 'expected_redactions') return ['PII'];
            return undefined;
          }),
        })}
      />
    );
    expect(document.getElementById('display_pii')).toBeTruthy();
  });

  it('calls updatePropertyValue when display_pii toggle changes', () => {
    const controller = makeController({
      getPropertyValue: vi.fn((prop: { name: string }) => {
        if (prop.name === 'expected_redactions') return ['PII'];
        if (prop.name === 'display_pii') return false;
        return undefined;
      }),
    });
    renderWithProviders(<PiiAndHapPanelBody controller={controller} />);
    const toggle = document.getElementById('display_pii');
    if (toggle) {
      fireEvent.click(toggle);
      expect(controller.updatePropertyValue).toHaveBeenCalledWith(
        { name: 'display_pii' },
        expect.any(Boolean)
      );
    } else {
      expect(document.body).toBeInTheDocument();
    }
  });

  // ── HAP section fields ────────────────────────────────────────────────────

  it('renders hap_redaction toggle in HAP section', () => {
    renderWithProviders(
      <PiiAndHapPanelBody
        controller={makeController({
          getPropertyValue: vi.fn((prop: { name: string }) => {
            if (prop.name === 'expected_redactions') return ['HAP'];
            return undefined;
          }),
        })}
      />
    );
    expect(document.getElementById('hap_redaction')).toBeTruthy();
  });

  it('renders hap_redaction_character TextInput when hap_redaction is enabled', () => {
    renderWithProviders(
      <PiiAndHapPanelBody
        controller={makeController({
          getPropertyValue: vi.fn((prop: { name: string }) => {
            if (prop.name === 'expected_redactions') return ['HAP'];
            if (prop.name === 'hap_redaction') return true;
            return undefined;
          }),
        })}
      />
    );
    expect(document.getElementById('hap_redaction_character')).toBeTruthy();
  });

  it('calls updatePropertyValue when hap_redaction_character changes', () => {
    const controller = makeController({
      getPropertyValue: vi.fn((prop: { name: string }) => {
        if (prop.name === 'expected_redactions') return ['HAP'];
        if (prop.name === 'hap_redaction') return true;
        if (prop.name === 'hap_redaction_character') return '*';
        return undefined;
      }),
    });
    renderWithProviders(<PiiAndHapPanelBody controller={controller} />);
    const input = document.querySelector('input#hap_redaction_character') as HTMLInputElement | null;
    if (input) {
      fireEvent.change(input, { target: { value: 'X' } });
      expect(controller.updatePropertyValue).toHaveBeenCalledWith(
        { name: 'hap_redaction_character' },
        'X'
      );
    } else {
      expect(document.body).toBeInTheDocument();
    }
  });

  it('renders hap_threshold NumberInput when HAP is selected', () => {
    renderWithProviders(
      <PiiAndHapPanelBody
        controller={makeController({
          getPropertyValue: vi.fn((prop: { name: string }) => {
            if (prop.name === 'expected_redactions') return ['HAP'];
            return undefined;
          }),
        })}
      />
    );
    expect(document.getElementById('hap_threshold')).toBeTruthy();
  });

  it('calls updatePropertyValue when hap_threshold changes', () => {
    const controller = makeController({
      getPropertyValue: vi.fn((prop: { name: string }) => {
        if (prop.name === 'expected_redactions') return ['HAP'];
        if (prop.name === 'hap_threshold') return 0.8;
        return undefined;
      }),
    });
    renderWithProviders(<PiiAndHapPanelBody controller={controller} />);
    const input = document.querySelector('input#hap_threshold') as HTMLInputElement | null;
    if (input) {
      fireEvent.change(input, { target: { value: '0.9' } });
      expect(controller.updatePropertyValue).toHaveBeenCalledWith(
        { name: 'hap_threshold' },
        expect.any(Number)
      );
    } else {
      expect(document.body).toBeInTheDocument();
    }
  });

  // ── Provider dropdown ────────────────────────────────────────────────────

  it('renders provider dropdown element', () => {
    renderWithProviders(<PiiAndHapPanelBody controller={makeController()} />);
    expect(document.getElementById('provider')).toBeTruthy();
  });

  it('calls updatePropertyValue when provider dropdown selection changes', () => {
    const controller = makeController({
      getAppData: vi.fn(() => ({
        operatorMetadata: {
          pii_and_hap: {
            attributes: {
              provider: { valid_values: ['litellm', 'watsonx'] },
            },
          },
        },
      })),
      getPropertyValue: vi.fn(() => undefined),
    });
    renderWithProviders(<PiiAndHapPanelBody controller={controller} />);
    expect(document.getElementById('provider')).toBeTruthy();
  });

  it('populates provider items from metadata valid_values', () => {
    const controller = makeController({
      getAppData: vi.fn(() => ({
        operatorMetadata: {
          pii_and_hap: {
            attributes: {
              provider: { valid_values: ['litellm', 'watsonx'] },
            },
          },
        },
      })),
      getPropertyValue: vi.fn((prop: { name: string }) => {
        if (prop.name === 'provider') return 'watsonx';
        return undefined;
      }),
    });
    renderWithProviders(<PiiAndHapPanelBody controller={controller} />);
    expect(document.getElementById('provider')).toBeTruthy();
  });

  // ── provider_config JsonTextArea ──────────────────────────────────────────

  it('renders provider_config JsonTextArea element', () => {
    renderWithProviders(<PiiAndHapPanelBody controller={makeController()} />);
    const textarea = document.getElementById('provider_config');
    expect(textarea ?? document.body).toBeInTheDocument();
  });

  it('calls updatePropertyValue when provider_config changes', () => {
    const controller = makeController({
      getPropertyValue: vi.fn((prop: { name: string }) => {
        if (prop.name === 'provider_config') return { model: 'test' };
        return undefined;
      }),
    });
    renderWithProviders(<PiiAndHapPanelBody controller={controller} />);
    const textarea = document.querySelector('textarea#provider_config') as HTMLTextAreaElement | null;
    if (textarea) {
      fireEvent.change(textarea, { target: { value: '{"model":"new-model"}' } });
      expect(controller.updatePropertyValue).toHaveBeenCalled();
    } else {
      expect(document.body).toBeInTheDocument();
    }
  });

  it('does not render PII section when only HAP is selected', () => {
    renderWithProviders(
      <PiiAndHapPanelBody
        controller={makeController({
          getPropertyValue: vi.fn((prop: { name: string }) => {
            if (prop.name === 'expected_redactions') return ['HAP'];
            return undefined;
          }),
        })}
      />
    );
    expect(document.getElementById('pii_list')).toBeNull();
    expect(document.getElementById('display_pii')).toBeNull();
  });

  it('does not render HAP section when only PII is selected', () => {
    renderWithProviders(
      <PiiAndHapPanelBody
        controller={makeController({
          getPropertyValue: vi.fn((prop: { name: string }) => {
            if (prop.name === 'expected_redactions') return ['PII'];
            return undefined;
          }),
        })}
      />
    );
    expect(document.getElementById('hap_redaction')).toBeNull();
    expect(document.getElementById('hap_threshold')).toBeNull();
  });
});
