import { act, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import * as authApi from '../api/auth.js';
import { SESSION_EXPIRED_EVENT } from '../api/client.js';
import useAuth from '../hooks/useAuth.js';
import { apiError, CUSTOMER, networkError } from '../test/renderWithAuth.jsx';
import { getToken, setToken } from '../utils/tokenStorage.js';
import { AuthProvider } from './AuthContext.jsx';

vi.mock('../api/auth.js', () => ({
  login: vi.fn(),
  register: vi.fn(),
  fetchCurrentUser: vi.fn(),
}));

function Probe() {
  const auth = useAuth();
  return (
    <div>
      <p data-testid="status">{auth.status}</p>
      <p data-testid="user">{auth.user?.email ?? 'none'}</p>
      <p data-testid="expired">{String(auth.sessionExpired)}</p>
      <button type="button" onClick={() => auth.login('casey@example.com', 'Password123')}>
        login
      </button>
      <button type="button" onClick={auth.logout}>
        logout
      </button>
      <button type="button" onClick={auth.retry}>
        retry
      </button>
    </div>
  );
}

function renderProvider() {
  render(
    <AuthProvider>
      <Probe />
    </AuthProvider>,
  );
}

const status = () => screen.getByTestId('status');

beforeEach(() => {
  vi.resetAllMocks();
});

describe('AuthProvider', () => {
  it('starts signed out without calling the API when no token is saved', () => {
    renderProvider();

    expect(status()).toHaveTextContent('anonymous');
    expect(authApi.fetchCurrentUser).not.toHaveBeenCalled();
  });

  it('restores the session from a saved token', async () => {
    setToken('saved-token');
    authApi.fetchCurrentUser.mockResolvedValue(CUSTOMER);

    renderProvider();

    expect(status()).toHaveTextContent('loading');
    await waitFor(() => expect(status()).toHaveTextContent('authenticated'));
    expect(screen.getByTestId('user')).toHaveTextContent(CUSTOMER.email);
  });

  it('discards a saved token that the API rejects', async () => {
    setToken('stale-token');
    authApi.fetchCurrentUser.mockRejectedValue(
      apiError(401, { code: 'not_authenticated', message: 'Token has expired' }),
    );

    renderProvider();

    await waitFor(() => expect(status()).toHaveTextContent('anonymous'));
    expect(getToken()).toBeNull();
    expect(screen.getByTestId('expired')).toHaveTextContent('true');
  });

  it('keeps the token and recovers via retry when the server was unreachable', async () => {
    setToken('saved-token');
    authApi.fetchCurrentUser.mockRejectedValueOnce(networkError()).mockResolvedValueOnce(CUSTOMER);

    renderProvider();
    await waitFor(() => expect(status()).toHaveTextContent('error'));
    expect(getToken()).toBe('saved-token');

    await userEvent.click(screen.getByRole('button', { name: 'retry' }));

    await waitFor(() => expect(status()).toHaveTextContent('authenticated'));
    expect(authApi.fetchCurrentUser).toHaveBeenCalledTimes(2);
  });

  it('saves the token returned by login', async () => {
    authApi.login.mockResolvedValue({ access_token: 'new-token', user: CUSTOMER });
    renderProvider();

    await userEvent.click(screen.getByRole('button', { name: 'login' }));

    await waitFor(() => expect(status()).toHaveTextContent('authenticated'));
    expect(authApi.login).toHaveBeenCalledWith('casey@example.com', 'Password123');
    expect(getToken()).toBe('new-token');
  });

  it('signs out when any API call reports the session has ended', async () => {
    setToken('saved-token');
    authApi.fetchCurrentUser.mockResolvedValue(CUSTOMER);
    renderProvider();
    await waitFor(() => expect(status()).toHaveTextContent('authenticated'));

    act(() => {
      window.dispatchEvent(new Event(SESSION_EXPIRED_EVENT));
    });

    expect(status()).toHaveTextContent('anonymous');
    expect(screen.getByTestId('user')).toHaveTextContent('none');
    expect(screen.getByTestId('expired')).toHaveTextContent('true');
  });

  it('logout forgets the token', async () => {
    authApi.login.mockResolvedValue({ access_token: 'new-token', user: CUSTOMER });
    renderProvider();
    await userEvent.click(screen.getByRole('button', { name: 'login' }));
    await waitFor(() => expect(status()).toHaveTextContent('authenticated'));

    await userEvent.click(screen.getByRole('button', { name: 'logout' }));

    expect(status()).toHaveTextContent('anonymous');
    expect(getToken()).toBeNull();
    expect(screen.getByTestId('expired')).toHaveTextContent('false');
  });
});
