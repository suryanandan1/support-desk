import { render } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { vi } from 'vitest';

import { AuthContext } from '../contexts/AuthContext.jsx';

export const CUSTOMER = {
  id: 1,
  email: 'casey@example.com',
  full_name: 'Casey Customer',
  role: 'customer',
  is_active: true,
  created_at: '2026-10-01T10:00:00Z',
  last_login_at: null,
};

/** Render `ui` inside a router with a fake auth state (no network involved). */
export function renderWithAuth(ui, { auth = {}, initialEntries = ['/'] } = {}) {
  const value = {
    user: null,
    status: 'anonymous',
    sessionExpired: false,
    login: vi.fn(),
    register: vi.fn(),
    logout: vi.fn(),
    retry: vi.fn(),
    ...auth,
  };
  const result = render(
    <AuthContext.Provider value={value}>
      <MemoryRouter initialEntries={initialEntries}>{ui}</MemoryRouter>
    </AuthContext.Provider>,
  );
  return { ...result, auth: value };
}

/** An error shaped like the ones axios throws for an API error response. */
export function apiError(status, error) {
  return Object.assign(new Error(`Request failed with status code ${status}`), {
    response: { status, data: { error } },
  });
}

export function networkError() {
  return Object.assign(new Error('Network Error'), { code: 'ERR_NETWORK' });
}
