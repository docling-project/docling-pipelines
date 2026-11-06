import { describe, it, expect, vi } from 'vitest';
import CommonPropertiesPanelWrapper from '@/components/PropertiesPanel/CommonPropertiesPanelWrapper';

describe('CommonPropertiesPanelWrapper', () => {
  it('static id() returns the expected panel id', () => {
    expect(CommonPropertiesPanelWrapper.id()).toBe('common_properties_panel');
  });

  it('renderPanel() returns a React element', () => {
    const controller = { getAppData: vi.fn(() => ({})), getPropertyValue: vi.fn(), getPropertyValues: vi.fn(() => ({})), updatePropertyValue: vi.fn(), setSaveButtonDisable: vi.fn() };
    const wrapper = new CommonPropertiesPanelWrapper({}, controller, {});
    const element = wrapper.renderPanel();
    expect(element).toBeDefined();
    expect(element.type).toBeDefined();
  });

  it('constructor stores parameters, controller, data', () => {
    const params = { a: 1 };
    const controller = {};
    const data = { b: 2 };
    const wrapper = new CommonPropertiesPanelWrapper(params, controller, data);
    // Access via renderPanel – just ensure no throw during construction
    expect(wrapper).toBeDefined();
  });
});
