import { afterEach, describe, expect, it, vi } from 'vitest';

import { getToken, setToken } from '../utils/tokenStorage.js';
import apiClient, { SESSION_EXPIRED_EVENT } from './client.js';

// Custom axios adapters stand in for the network.
function respondOk(capture) {
  return async (config) => {
    capture?.(config);
    return { data: {}, status: 200, statusText: 'OK', headers: {}, config };
  };
}

function respondWith(status) {
  return async (config) => {
    throw Object.assign(new Error(`Request failed with status code ${status}`), {
      config,
      response: { status, data: {}, headers: {}, config },
    });
  };
}

describe('apiClient', () => {
  const onExpired = vi.fn();
  window.addEventListener(SESSION_EXPIRED_EVENT, onExpired);

  afterEach(() => {
    onExpired.mockClear();
  });

  it('attaches the saved token to requests', async () => {
    setToken('abc123');
    let sentHeader;

    await apiClient.get('/auth/me', {
      adapter: respondOk((config) => {
        sentHeader = config.headers.Authorization;
      }),
    });

    expect(sentHeader).toBe('Bearer abc123');
  });

  it('sends no Authorization header when signed out', async () => {
    let sentHeader = 'unset';

    await apiClient.get('/health', {
      adapter: respondOk((config) => {
        sentHeader = config.headers.Authorization;
      }),
    });

    expect(sentHeader).toBeUndefined();
  });

  it('ends the session when an authenticated request gets a 401', async () => {
    setToken('abc123');

    await expect(apiClient.get('/auth/me', { adapter: respondWith(401) })).rejects.toThrow();

    expect(getToken()).toBeNull();
    expect(onExpired).toHaveBeenCalledOnce();
  });

  it('does not treat a failed login (no token sent) as an expired session', async () => {
    await expect(apiClient.post('/auth/login', {}, { adapter: respondWith(401) })).rejects.toThrow();

    expect(onExpired).not.toHaveBeenCalled();
  });

  it('keeps the session for other errors', async () => {
    setToken('abc123');

    await expect(apiClient.get('/users', { adapter: respondWith(403) })).rejects.toThrow();
    await expect(apiClient.get('/users', { adapter: respondWith(500) })).rejects.toThrow();

    expect(getToken()).toBe('abc123');
    expect(onExpired).not.toHaveBeenCalled();
  });
});
