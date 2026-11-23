import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, fireEvent } from '@testing-library/react';
import { renderWithProviders } from '../../../../../utils/renderWithProviders';
import { WeaviateConnectionFields } from '@/components/PropertiesPanel/CustomPanels/VectorDB/WeaviateConnectionFields';
import { WeaviateAuthFields } from '@/components/PropertiesPanel/CustomPanels/VectorDB/WeaviateAuthFields';

const onChange = vi.fn();

const openDropdown = (name: RegExp): void => {
  fireEvent.click(screen.getByRole('combobox', { name }));
};

const tlsAlert = (): HTMLElement | undefined =>
  screen.queryAllByRole('alert').find((el) => /both http and grpc/i.test(el.textContent ?? ''));

describe('WeaviateConnectionFields', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    Element.prototype.scrollIntoView = vi.fn();
  });

  it('shows the on-prem controls and no cluster URL by default', () => {
    renderWithProviders(<WeaviateConnectionFields config={{}} errors={{}} onChange={onChange} />);

    expect(document.getElementById('weaviate-host')).toBeInTheDocument();
    expect(document.getElementById('weaviate-port')).toBeInTheDocument();
    expect(document.getElementById('weaviate-grpc-port')).toBeInTheDocument();
    expect(document.getElementById('weaviate-cluster-url')).toBeNull();
  });

  it('shows only the cluster URL for a cloud connection', () => {
    renderWithProviders(
      <WeaviateConnectionFields config={{ connection_type: 'cloud' }} errors={{}} onChange={onChange} />
    );

    expect(document.getElementById('weaviate-cluster-url')).toBeInTheDocument();
    expect(document.getElementById('weaviate-host')).toBeNull();
    expect(document.getElementById('weaviate-port')).toBeNull();
  });

  it('reports a connection type switch as one complete configuration without the other mode keys', () => {
    renderWithProviders(
      <WeaviateConnectionFields
        config={{ connection_type: 'on-prem', host: 'db', port: 8080, grpc_port: 50051, collection_name: 'Docs' }}
        errors={{}}
        onChange={onChange}
      />
    );

    openDropdown(/connection type/i);
    fireEvent.click(screen.getByRole('option', { name: 'Weaviate Cloud' }));

    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange).toHaveBeenCalledWith({ connection_type: 'cloud', collection_name: 'Docs' });
  });

  it('reports an HTTP port edit as a number', () => {
    renderWithProviders(<WeaviateConnectionFields config={{}} errors={{}} onChange={onChange} />);

    fireEvent.change(document.getElementById('weaviate-port') as HTMLElement, { target: { value: '9090' } });

    expect(onChange).toHaveBeenCalledWith({ port: 9090 });
  });

  it('keeps a non-numeric port as text so validation can reject it', () => {
    renderWithProviders(<WeaviateConnectionFields config={{}} errors={{}} onChange={onChange} />);

    fireEvent.change(document.getElementById('weaviate-port') as HTMLElement, { target: { value: 'abc' } });

    expect(onChange).toHaveBeenCalledWith({ port: 'abc' });
  });

  it('removes the gRPC host override when the field is emptied so it inherits the HTTP host', () => {
    renderWithProviders(
      <WeaviateConnectionFields config={{ grpc_host: 'grpc.internal' }} errors={{}} onChange={onChange} />
    );

    fireEvent.change(document.getElementById('weaviate-grpc-host') as HTMLElement, { target: { value: '' } });

    expect(onChange).toHaveBeenCalledWith({});
  });

  it('writes an explicit gRPC TLS override and clears it for "Same as HTTP"', () => {
    const { rerender } = renderWithProviders(
      <WeaviateConnectionFields config={{}} errors={{}} onChange={onChange} />
    );

    openDropdown(/grpc tls/i);
    fireEvent.click(screen.getByRole('option', { name: 'On' }));
    expect(onChange).toHaveBeenLastCalledWith({ grpc_secure: true });

    rerender(<WeaviateConnectionFields config={{ grpc_secure: true }} errors={{}} onChange={onChange} />);
    openDropdown(/grpc tls/i);
    fireEvent.click(screen.getByRole('option', { name: 'Same as HTTP' }));
    expect(onChange).toHaveBeenLastCalledWith({});
  });

  it('toggles HTTP TLS through the labelled switch', () => {
    renderWithProviders(<WeaviateConnectionFields config={{}} errors={{}} onChange={onChange} />);

    fireEvent.click(screen.getByRole('switch', { name: /http tls/i }));

    expect(onChange).toHaveBeenCalledWith({ secure: true });
  });

  it('shows the field error text on an invalid host', () => {
    renderWithProviders(
      <WeaviateConnectionFields config={{ host: '' }} errors={{ host: 'required' }} onChange={onChange} />
    );

    expect(screen.getByText('This field is required')).toBeInTheDocument();
    expect(document.getElementById('weaviate-host')).toHaveAttribute('aria-invalid', 'true');
  });

  it('shows a TLS alert when authentication is configured without TLS', () => {
    renderWithProviders(
      <WeaviateConnectionFields
        config={{ auth_type: 'api_key' }}
        errors={{ secure: 'tls_required', grpc_secure: 'tls_required' }}
        onChange={onChange}
      />
    );

    expect(tlsAlert()).toBeDefined();
    expect(screen.getByRole('switch', { name: /http tls/i })).toHaveAttribute('aria-invalid', 'true');
  });

  it('does not show the TLS alert for other errors', () => {
    renderWithProviders(
      <WeaviateConnectionFields config={{}} errors={{ host: 'required' }} onChange={onChange} />
    );

    expect(tlsAlert()).toBeUndefined();
  });
});

describe('WeaviateAuthFields', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    Element.prototype.scrollIntoView = vi.fn();
  });

  it('shows no credential input when authentication is off', () => {
    renderWithProviders(<WeaviateAuthFields config={{}} errors={{}} onChange={onChange} />);

    expect(document.getElementById('weaviate-api-key')).toBeNull();
    expect(document.getElementById('weaviate-bearer-token')).toBeNull();
    expect(document.getElementById('weaviate-username')).toBeNull();
    expect(document.getElementById('weaviate-password')).toBeNull();
  });

  it('shows only the API key input for the API key method', () => {
    renderWithProviders(
      <WeaviateAuthFields config={{ auth_type: 'api_key' }} errors={{}} onChange={onChange} />
    );

    expect(document.getElementById('weaviate-api-key')).toBeInTheDocument();
    expect(document.getElementById('weaviate-bearer-token')).toBeNull();
  });

  it('shows username and password for the username and password method', () => {
    renderWithProviders(
      <WeaviateAuthFields config={{ auth_type: 'client_password' }} errors={{}} onChange={onChange} />
    );

    expect(document.getElementById('weaviate-username')).toBeInTheDocument();
    expect(document.getElementById('weaviate-password')).toBeInTheDocument();
  });

  it('shows the username unmasked with a Vault toggle and keeps the password masked', () => {
    renderWithProviders(
      <WeaviateAuthFields
        config={{ auth_type: 'client_password', username: 'alice', password: 'pw' }}
        errors={{}}
        onChange={onChange}
      />
    );

    expect(document.getElementById('weaviate-username')).toHaveAttribute('type', 'text');
    expect(document.getElementById('weaviate-username')).toHaveValue('alice');
    expect(document.getElementById('weaviate-password')).toHaveAttribute('type', 'password');
    expect(document.getElementById('weaviate-username-vault-toggle')).toBeInTheDocument();
    expect(document.getElementById('weaviate-password-vault-toggle')).toBeInTheDocument();
  });

  it('masks a directly typed credential', () => {
    renderWithProviders(
      <WeaviateAuthFields config={{ auth_type: 'api_key', api_key: 'secret' }} errors={{}} onChange={onChange} />
    );

    expect(document.getElementById('weaviate-api-key')).toHaveAttribute('type', 'password');
  });

  it('reports a method switch as one complete configuration without the previous credentials', () => {
    renderWithProviders(
      <WeaviateAuthFields
        config={{ auth_type: 'api_key', api_key: 'secret', host: 'db' }}
        errors={{}}
        onChange={onChange}
      />
    );

    openDropdown(/authentication method/i);
    fireEvent.click(screen.getByRole('option', { name: 'Bearer token' }));

    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange).toHaveBeenCalledWith({ auth_type: 'bearer_token', host: 'db' });
  });

  it('reports a credential edit with the rest of the configuration preserved', () => {
    renderWithProviders(
      <WeaviateAuthFields config={{ auth_type: 'api_key', host: 'db' }} errors={{}} onChange={onChange} />
    );

    fireEvent.change(document.getElementById('weaviate-api-key') as HTMLElement, { target: { value: 'k' } });

    expect(onChange).toHaveBeenCalledWith({ auth_type: 'api_key', host: 'db', api_key: 'k' });
  });

  it('shows the field error on a missing credential', () => {
    renderWithProviders(
      <WeaviateAuthFields
        config={{ auth_type: 'client_password' }}
        errors={{ username: 'required', password: 'required' }}
        onChange={onChange}
      />
    );

    expect(screen.getAllByText('This field is required')).toHaveLength(2);
  });
});
