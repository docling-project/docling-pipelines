import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, fireEvent, waitFor, within } from '@testing-library/react';
import { renderWithProviders } from '../../../utils/renderWithProviders';
import { Login } from '@/pages/Login/Login';

// Mock window.location.assign
const mockAssign = vi.fn();
Object.defineProperty(window, 'location', {
  value: { assign: mockAssign },
  writable: true,
});

const mockLogin = vi.fn();
vi.mock('@/services/api/actions/auth-actions', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/services/api/actions/auth-actions')>()),
  login: (...args: unknown[]) => mockLogin(...args),
}));

vi.mock('@carbon-labs/react-animated-header/es/components/AnimatedBackground/AnimatedBackground', () => ({
  default: () => <div data-testid="mock-animated-background" />,
}));

/** Unauthenticated auth state with credential login enabled. */
function credentialAuth() {
  return {
    user: null,
    authEnabled: true,
    providers: [],
    credentialLogin: true,
    status: 'unauthenticated' as const,
    error: null,
    errorStatus: null,
    retryAfter: null,
  };
}

/** Renders the Login component and awaits lazy-loaded artwork. */
async function renderLogin(options?: Parameters<typeof renderWithProviders>[1]) {
  const result = renderWithProviders(<Login />, options);
  await screen.findByTestId('mock-animated-background');
  return result;
}

describe('Login page', () => {
  beforeEach(() => {
    mockAssign.mockClear();
    mockLogin.mockReset();
  });

  it('renders correctly when credential login is available', async () => {
    await renderLogin({
      preloadedState: {
        auth: credentialAuth(),
      },
    });

    expect(screen.getByText('Docling Pipelines')).toBeDefined();
    expect(screen.getByRole('heading', { name: 'Log in' })).toBeDefined();
    expect(screen.getAllByRole('heading', { level: 1 })).toHaveLength(1);
    expect(screen.getByLabelText('Username')).toBeDefined();
    expect(screen.getByLabelText('Password')).toBeDefined();
    expect(screen.getByRole('button', { name: 'Log in' })).toBeDefined();
  });

  describe('header and illustration', () => {
    beforeEach(() => {
      window.localStorage.clear();
    });

    it('renders the product name as a non-link label with the Beta tag', async () => {
      await renderLogin({ preloadedState: { auth: credentialAuth() } });

      const banner = screen.getByRole('banner');
      expect(within(banner).getByText('Docling Pipelines')).toBeDefined();
      expect(within(banner).getByText('Beta')).toBeDefined();
      expect(within(banner).queryAllByRole('link')).toHaveLength(0);
      expect(within(banner).queryAllByRole('navigation')).toHaveLength(0);
    });

    it('does not repeat the product name as a heading in the brand panel', async () => {
      await renderLogin({ preloadedState: { auth: credentialAuth() } });

      expect(screen.getAllByText('Docling Pipelines')).toHaveLength(1);
      expect(screen.getAllByRole('heading', { level: 1 })).toHaveLength(1);
    });

    it('toggles the theme through the header action', async () => {
      await renderLogin({ preloadedState: { auth: credentialAuth() } });

      const banner = screen.getByRole('banner');
      const toggle = within(banner).getByRole('button', { name: /Switch to (light|dark) mode/ });
      const before = toggle.getAttribute('aria-label');
      fireEvent.click(toggle);
      const after = within(banner)
        .getByRole('button', { name: /Switch to (light|dark) mode/ })
        .getAttribute('aria-label');

      expect(after).not.toBe(before);
    });

    it('has no notification bell or user menu in the header', async () => {
      await renderLogin({ preloadedState: { auth: credentialAuth() } });

      const banner = screen.getByRole('banner');
      expect(within(banner).queryByRole('button', { name: /Notifications/ })).toBeNull();
      expect(within(banner).queryByText('Sign out')).toBeNull();
      expect(within(banner).queryByText('User menu')).toBeNull();
      expect(within(banner).getAllByRole('button')).toHaveLength(1);
    });

    it('renders the illustration wrapper hidden from assistive technology', async () => {
      await renderLogin({ preloadedState: { auth: credentialAuth() } });

      const wrapper = screen.getByTestId('login-illustration-wrapper');
      expect(wrapper.getAttribute('aria-hidden')).toBe('true');
    });
  });

  it('renders the brand tagline, helper text and footer', async () => {
    await renderLogin({ preloadedState: { auth: credentialAuth() } });

    expect(screen.getByText('Build, run and monitor document processing pipelines.')).toBeDefined();
    expect(screen.getByText('Enter your credentials to continue.')).toBeDefined();
    expect(screen.getByText('Need access? Contact your administrator.')).toBeDefined();
  });

  it('configures autocomplete, autofocus and a correct password placeholder', async () => {
    await renderLogin({ preloadedState: { auth: credentialAuth() } });

    const username = screen.getByLabelText('Username');
    const password = screen.getByLabelText('Password');
    expect(username.getAttribute('autocomplete')).toBe('username');
    expect(document.activeElement).toBe(username);
    expect(password.getAttribute('autocomplete')).toBe('current-password');
    expect(screen.getByPlaceholderText('Enter password')).toBe(password);
  });

  describe('validation on blur and submit', () => {
    it('shows inline required error on blur when username is empty and clears on input', async () => {
      await renderLogin({ preloadedState: { auth: credentialAuth() } });

      const usernameInput = screen.getByLabelText('Username');
      fireEvent.blur(usernameInput);

      expect(screen.getByText('Username is required.')).toBeDefined();

      fireEvent.change(usernameInput, { target: { value: 'alice' } });
      expect(screen.queryByText('Username is required.')).toBeNull();
    });

    it('shows inline required error on blur when password is empty and clears on input', async () => {
      await renderLogin({ preloadedState: { auth: credentialAuth() } });

      const passwordInput = screen.getByLabelText('Password');
      fireEvent.blur(passwordInput);

      expect(screen.getByText('Password is required.')).toBeDefined();

      fireEvent.change(passwordInput, { target: { value: 'secret' } });
      expect(screen.queryByText('Password is required.')).toBeNull();
    });

    it('shows error if submitted with empty fields', async () => {
      await renderLogin({ preloadedState: { auth: credentialAuth() } });

      const submitBtn = screen.getByRole('button', { name: 'Log in' });
      fireEvent.click(submitBtn);

      expect(screen.getByText('Username is required.')).toBeDefined();
      expect(screen.getByText('Password is required.')).toBeDefined();
    });
  });

  describe('post-login behavior', () => {
    it('clears password and focuses username input after a failed server login while retaining username', async () => {
      mockLogin.mockRejectedValue({
        response: {
          status: 401,
          data: { detail: 'Invalid username or password' },
        },
      });

      await renderLogin({ preloadedState: { auth: credentialAuth() } });

      const usernameInput = screen.getByLabelText('Username') as HTMLInputElement;
      const passwordInput = screen.getByLabelText('Password') as HTMLInputElement;

      fireEvent.change(usernameInput, { target: { value: 'alice' } });
      fireEvent.change(passwordInput, { target: { value: 'wrong-password' } });
      fireEvent.click(screen.getByRole('button', { name: 'Log in' }));

      await waitFor(() => {
        expect(screen.getByText('Invalid username or password')).toBeDefined();
      });

      expect(usernameInput.value).toBe('alice');
      expect(passwordInput.value).toBe('');
      expect(document.activeElement).toBe(usernameInput);
    });

    it('does not clear password when submission is in progress or succeeds', async () => {
      mockLogin.mockResolvedValue({
        data: {
          user: {
            username: 'alice',
            email: 'alice@example.com',
            full_name: 'Alice Smith',
            roles: ['viewer'],
          },
        },
      });

      await renderLogin({ preloadedState: { auth: credentialAuth() } });

      const usernameInput = screen.getByLabelText('Username') as HTMLInputElement;
      const passwordInput = screen.getByLabelText('Password') as HTMLInputElement;

      fireEvent.change(usernameInput, { target: { value: 'alice' } });
      fireEvent.change(passwordInput, { target: { value: 'valid-secret' } });
      fireEvent.click(screen.getByRole('button', { name: 'Log in' }));

      await waitFor(() => {
        expect(mockLogin).toHaveBeenCalledWith({ username: 'alice', password: 'valid-secret' });
      });

      expect(passwordInput.value).toBe('valid-secret');
    });
  });

  it('shows an inline loading state and disables the form while submitting', async () => {
    mockLogin.mockReturnValue(new Promise(() => undefined));
    await renderLogin({ preloadedState: { auth: credentialAuth() } });

    fireEvent.change(screen.getByLabelText('Username'), { target: { value: 'alice' } });
    fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'secret' } });
    fireEvent.click(screen.getByRole('button', { name: 'Log in' }));

    await waitFor(() => {
      expect(screen.getByText('Logging in...')).toBeDefined();
    });
    expect(mockLogin).toHaveBeenCalledWith({ username: 'alice', password: 'secret' });
    expect(screen.queryByRole('button', { name: 'Log in' })).toBeNull();
    expect(screen.getByRole('button', { name: /Logging in/ }).hasAttribute('disabled')).toBe(true);
    expect(screen.getByLabelText('Username').hasAttribute('disabled')).toBe(true);
  });

  it('shows server error when 401 occurs', async () => {
    await renderLogin({
      preloadedState: {
        auth: {
          user: null,
          authEnabled: true,
          providers: [],
          credentialLogin: true,
          status: 'unauthenticated',
          error: 'Invalid credentials',
          errorStatus: 401,
          retryAfter: null,
        },
      },
    });

    expect(screen.getByText('Invalid credentials')).toBeDefined();
  });

  it('shows retry later message on 429 error', async () => {
    await renderLogin({
      preloadedState: {
        auth: {
          user: null,
          authEnabled: true,
          providers: [],
          credentialLogin: true,
          status: 'unauthenticated',
          error: 'Too many requests',
          errorStatus: 429,
          retryAfter: 60,
        },
      },
    });

    expect(screen.getByText('Too many failed attempts. Please retry later.')).toBeDefined();
  });

  it('shows no login method configured warning when neither is available', async () => {
    await renderLogin({
      preloadedState: {
        auth: {
          user: null,
          authEnabled: true,
          providers: [],
          credentialLogin: false,
          status: 'unauthenticated',
          error: null,
          errorStatus: null,
          retryAfter: null,
        },
      },
    });

    expect(screen.getByText('No login method is currently configured.')).toBeDefined();
  });

  it('hides form and shows provider buttons when OIDC is configured and credentials disabled', async () => {
    await renderLogin({
      preloadedState: {
        auth: {
          user: null,
          authEnabled: true,
          providers: [{ name: 'google', display_name: 'Google', authorize_url: '/auth/oauth2/authorize?provider=google' }],
          credentialLogin: false,
          status: 'unauthenticated',
          error: null,
          errorStatus: null,
          retryAfter: null,
        },
      },
    });

    expect(screen.queryByLabelText('Username')).toBeNull();
    expect(screen.getByText('Log in with Google')).toBeDefined();
  });

  it('navigates to authorize URL with return_to parameter when provider is selected', async () => {
    await renderLogin({
      initialEntries: ['/login?return_to=%2Fflows%2F123'],
      preloadedState: {
        auth: {
          user: null,
          authEnabled: true,
          providers: [{ name: 'google', display_name: 'Google', authorize_url: '/auth/oauth2/authorize?provider=google' }],
          credentialLogin: false,
          status: 'unauthenticated',
          error: null,
          errorStatus: null,
          retryAfter: null,
        },
      },
    });

    const btn = screen.getByRole('button', { name: 'Log in with Google' });
    fireEvent.click(btn);

    expect(mockAssign).toHaveBeenCalledWith('/auth/oauth2/authorize?provider=google&return_to=%2Fflows%2F123');
  });

  it('rejects unsafe provider authorize_url schemes and protocol-relative URLs', async () => {
    await renderLogin({
      preloadedState: {
        auth: {
          user: null,
          authEnabled: true,
          providers: [
            { name: 'evil-js', display_name: 'EvilJS', authorize_url: 'javascript:alert(1)' },
            { name: 'evil-rel', display_name: 'EvilRel', authorize_url: '//evil.com/auth' },
            { name: 'safe-https', display_name: 'SafeIdP', authorize_url: 'https://idp.example.com/authorize' },
          ],
          credentialLogin: false,
          status: 'unauthenticated',
          error: null,
          errorStatus: null,
          retryAfter: null,
        },
      },
    });

    fireEvent.click(screen.getByRole('button', { name: 'Log in with EvilJS' }));
    fireEvent.click(screen.getByRole('button', { name: 'Log in with EvilRel' }));
    expect(mockAssign).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole('button', { name: 'Log in with SafeIdP' }));
    expect(mockAssign).toHaveBeenCalledWith('https://idp.example.com/authorize?return_to=%2Fprojects');
  });

  it('has error notification with alert role for accessibility', async () => {
    await renderLogin({
      preloadedState: {
        auth: {
          user: null,
          authEnabled: true,
          providers: [],
          credentialLogin: true,
          status: 'unauthenticated',
          error: 'Invalid username/password',
          errorStatus: 401,
          retryAfter: null,
        },
      },
    });

    const alerts = screen.getAllByRole('alert');
    const notificationAlert = alerts.find((el) => el.textContent?.includes('Invalid username/password'));
    expect(notificationAlert).toBeDefined();
  });
});
