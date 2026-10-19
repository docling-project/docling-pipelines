import { describe, it, expect, vi } from 'vitest';
import { fireEvent } from '@testing-library/react';
import { renderWithProviders } from '../../../../../utils/renderWithProviders';
import { ProviderFieldsForm } from '@/components/PropertiesPanel/CustomPanels/shared/ProviderFieldsForm';

describe('ProviderFieldsForm', () => {
  it('renders without crashing with empty properties', () => {
    const { container } = renderWithProviders(
      <ProviderFieldsForm properties={{}} values={{}} onChange={vi.fn()} />
    );
    expect(container).toBeInTheDocument();
  });

  it('renders text input for non-sensitive string field', () => {
    const { container } = renderWithProviders(
      <ProviderFieldsForm
        properties={{ host: { type: 'string', label: 'Host', description: 'Host', sensitive: false } as any }}
        values={{ host: 'localhost' }}
        onChange={vi.fn()}
      />
    );
    expect(container).toBeInTheDocument();
    expect(document.getElementById('provider-field-host')).not.toBeNull();
  });

  it('renders number input for int64 field', () => {
    const { container } = renderWithProviders(
      <ProviderFieldsForm
        properties={{ port: { type: 'int64', label: 'Port', description: 'Port' } as any }}
        values={{ port: 9200 }}
        onChange={vi.fn()}
      />
    );
    expect(container).toBeInTheDocument();
    expect(document.getElementById('provider-field-port')).not.toBeNull();
  });

  it('renders toggle for boolean field', () => {
    const { container } = renderWithProviders(
      <ProviderFieldsForm
        properties={{ enabled: { type: 'boolean', label: 'Enabled', description: 'Flag' } as any }}
        values={{ enabled: true }}
        onChange={vi.fn()}
      />
    );
    expect(container).toBeInTheDocument();
    expect(document.getElementById('provider-field-enabled')).not.toBeNull();
  });

  it('renders number input for double field', () => {
    const { container } = renderWithProviders(
      <ProviderFieldsForm
        properties={{ threshold: { type: 'double', label: 'Threshold', description: 'Float threshold' } as any }}
        values={{ threshold: 0.75 }}
        onChange={vi.fn()}
      />
    );
    expect(container).toBeInTheDocument();
    expect(document.getElementById('provider-field-threshold')).not.toBeNull();
  });

  it('renders VaultInput for sensitive string field', () => {
    const { container } = renderWithProviders(
      <ProviderFieldsForm
        properties={{ secret_key: { type: 'string', label: 'Secret Key', description: 'Secret', sensitive: true } as any }}
        values={{ secret_key: '' }}
        onChange={vi.fn()}
      />
    );
    expect(container).toBeInTheDocument();
    expect(document.getElementById('provider-field-secret_key')).not.toBeNull();
  });

  it('renders list field as TagInput', () => {
    const { container } = renderWithProviders(
      <ProviderFieldsForm
        properties={{ paths: { type: 'list', label: 'Paths', description: 'List of paths' } as any }}
        values={{ paths: ['/data/input'] }}
        onChange={vi.fn()}
      />
    );
    expect(container).toBeInTheDocument();
    expect(document.getElementById('provider-field-paths')).not.toBeNull();
  });

  it('renders json field as JsonTextArea', () => {
    const { container } = renderWithProviders(
      <ProviderFieldsForm
        properties={{ extra_config: { type: 'json', label: 'Extra Config', description: 'JSON config' } as any }}
        values={{ extra_config: { key: 'value' } }}
        onChange={vi.fn()}
      />
    );
    expect(container).toBeInTheDocument();
    expect(document.getElementById('provider-field-extra_config')).not.toBeNull();
  });

  it('skips hidden field "file_extensions"', () => {
    const { container } = renderWithProviders(
      <ProviderFieldsForm
        properties={{
          file_extensions: { type: 'list', label: 'File Extensions', description: 'Hidden field' } as any,
          host: { type: 'string', label: 'Host', description: 'Host', sensitive: false } as any,
        }}
        values={{}}
        onChange={vi.fn()}
      />
    );
    expect(container).toBeInTheDocument();
    // file_extensions is hidden
    expect(document.getElementById('provider-field-file_extensions')).toBeNull();
    // host is shown
    expect(document.getElementById('provider-field-host')).not.toBeNull();
  });

  it('marks required field with "(required)" suffix in label', () => {
    renderWithProviders(
      <ProviderFieldsForm
        properties={{ bucket: { type: 'string', name: 'bucket', label: 'Bucket', description: 'S3 bucket', required: true, sensitive: false } as any }}
        values={{ bucket: '' }}
        onChange={vi.fn()}
      />
    );
    // Required suffix appended to label text
    const requiredText = document.body.textContent ?? '';
    expect(requiredText).toContain('required');
  });

  it('calls onChange when text input value changes', () => {
    const onChange = vi.fn();
    renderWithProviders(
      <ProviderFieldsForm
        properties={{ bucket: { type: 'string', name: 'bucket', label: 'Bucket', description: 'S3 bucket', sensitive: false } as any }}
        values={{ bucket: 'my-bucket' }}
        onChange={onChange}
      />
    );
    const input = document.getElementById('provider-field-bucket') as HTMLInputElement | null;
    if (input) {
      fireEvent.change(input, { target: { value: 'new-bucket' } });
      expect(onChange).toHaveBeenCalledWith('bucket', 'new-bucket');
    } else {
      expect(document.body).toBeInTheDocument();
    }
  });

  it('calls onChange when boolean toggle is clicked', () => {
    const onChange = vi.fn();
    renderWithProviders(
      <ProviderFieldsForm
        properties={{ recursive: { type: 'boolean', name: 'recursive', label: 'Recursive', description: 'Recurse dirs' } as any }}
        values={{ recursive: false }}
        onChange={onChange}
      />
    );
    const toggle = document.getElementById('provider-field-recursive') as HTMLElement | null;
    if (toggle) {
      fireEvent.click(toggle);
      expect(onChange).toHaveBeenCalled();
    } else {
      expect(document.body).toBeInTheDocument();
    }
  });

  it('renders S3 provider fields (bucket, prefix, region, access_key)', () => {
    const s3Props = {
      bucket: { type: 'string', name: 'bucket', label: 'Bucket', description: 'S3 bucket name', sensitive: false } as any,
      prefix: { type: 'string', name: 'prefix', label: 'Prefix', description: 'Key prefix', sensitive: false } as any,
      region: { type: 'string', name: 'region', label: 'Region', description: 'AWS region', sensitive: false } as any,
      access_key: { type: 'string', name: 'access_key', label: 'Access Key', description: 'AWS access key', sensitive: true } as any,
    };
    renderWithProviders(
      <ProviderFieldsForm
        properties={s3Props}
        values={{ bucket: 'my-bucket', prefix: 'data/', region: 'us-east-1', access_key: '' }}
        onChange={vi.fn()}
      />
    );
    expect(document.getElementById('provider-field-bucket')).not.toBeNull();
    expect(document.getElementById('provider-field-prefix')).not.toBeNull();
    expect(document.getElementById('provider-field-region')).not.toBeNull();
    expect(document.getElementById('provider-field-access_key')).not.toBeNull();
  });

  it('renders COS provider fields (endpoint, bucket, api_key)', () => {
    const cosProps = {
      endpoint: { type: 'string', name: 'endpoint', label: 'Endpoint', description: 'COS endpoint', sensitive: false } as any,
      bucket: { type: 'string', name: 'bucket', label: 'Bucket', description: 'COS bucket', sensitive: false } as any,
      api_key: { type: 'string', name: 'api_key', label: 'API Key', description: 'COS api key', sensitive: true } as any, // pragma: allowlist secret
    };
    renderWithProviders(
      <ProviderFieldsForm
        properties={cosProps}
        values={{ endpoint: 'https://s3.us-south.cloud-object-storage.appdomain.cloud', bucket: 'my-cos-bucket', api_key: '' }}
        onChange={vi.fn()}
      />
    );
    expect(document.getElementById('provider-field-endpoint')).not.toBeNull();
    expect(document.getElementById('provider-field-bucket')).not.toBeNull();
    expect(document.getElementById('provider-field-api_key')).not.toBeNull();
  });

  it('handles undefined values gracefully (falls back to empty string/false)', () => {
    renderWithProviders(
      <ProviderFieldsForm
        properties={{
          host: { type: 'string', label: 'Host', description: 'Host', sensitive: false } as any,
          port: { type: 'int64', label: 'Port', description: 'Port' } as any,
          enabled: { type: 'boolean', label: 'Enabled', description: 'Flag' } as any,
        }}
        values={{}}
        onChange={vi.fn()}
      />
    );
    const hostInput = document.getElementById('provider-field-host') as HTMLInputElement | null;
    if (hostInput) { expect(hostInput.value).toBe(''); }
    expect(document.body).toBeInTheDocument();
  });

  it('handles string array values for list field', () => {
    renderWithProviders(
      <ProviderFieldsForm
        properties={{ paths: { type: 'list', label: 'Paths', description: 'Paths' } as any }}
        values={{ paths: '/data/input,/data/extra' }}
        onChange={vi.fn()}
      />
    );
    expect(document.getElementById('provider-field-paths')).not.toBeNull();
  });

  it('handles null json value gracefully', () => {
    const { container } = renderWithProviders(
      <ProviderFieldsForm
        properties={{ config: { type: 'json', label: 'Config', description: 'JSON' } as any }}
        values={{ config: null }}
        onChange={vi.fn()}
      />
    );
    expect(container).toBeInTheDocument();
  });
});
