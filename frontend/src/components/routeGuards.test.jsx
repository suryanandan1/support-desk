import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Route, Routes } from 'react-router';
import { describe, expect, it } from 'vitest';

import { CUSTOMER, renderWithAuth } from '../test/renderWithAuth.jsx';
import ProtectedRoute from './ProtectedRoute.jsx';
import PublicOnlyRoute from './PublicOnlyRoute.jsx';

function AppRoutes({ roles }) {
  return (
    <Routes>
      <Route element={<PublicOnlyRoute />}>
        <Route path="/login" element={<p>Login page</p>} />
      </Route>
      <Route element={<ProtectedRoute roles={roles} />}>
        <Route path="/" element={<p>Dashboard page</p>} />
        <Route path="/tickets" element={<p>Tickets page</p>} />
      </Route>
    </Routes>
  );
}

describe('ProtectedRoute', () => {
  it('sends signed-out visitors to the login page', () => {
    renderWithAuth(<AppRoutes />, { initialEntries: ['/tickets'] });

    expect(screen.getByText('Login page')).toBeInTheDocument();
    expect(screen.queryByText('Tickets page')).not.toBeInTheDocument();
  });

  it('shows a spinner while the saved session is being checked', () => {
    renderWithAuth(<AppRoutes />, { auth: { status: 'loading' } });

    expect(screen.getByRole('status')).toHaveTextContent('Checking your session');
    expect(screen.queryByText('Dashboard page')).not.toBeInTheDocument();
  });

  it('offers a retry when the server cannot be reached', async () => {
    const { auth } = renderWithAuth(<AppRoutes />, { auth: { status: 'error' } });

    await userEvent.click(screen.getByRole('button', { name: 'Retry' }));

    expect(auth.retry).toHaveBeenCalledOnce();
    expect(screen.queryByText('Dashboard page')).not.toBeInTheDocument();
  });

  it('renders the page for a signed-in user', () => {
    renderWithAuth(<AppRoutes />, { auth: { status: 'authenticated', user: CUSTOMER } });

    expect(screen.getByText('Dashboard page')).toBeInTheDocument();
  });

  it('blocks users whose role is not allowed', () => {
    renderWithAuth(<AppRoutes roles={['admin']} />, {
      auth: { status: 'authenticated', user: CUSTOMER },
    });

    expect(screen.getByText('Access denied')).toBeInTheDocument();
    expect(screen.queryByText('Dashboard page')).not.toBeInTheDocument();
  });

  it('allows users whose role is listed', () => {
    renderWithAuth(<AppRoutes roles={['customer', 'admin']} />, {
      auth: { status: 'authenticated', user: CUSTOMER },
    });

    expect(screen.getByText('Dashboard page')).toBeInTheDocument();
  });
});

describe('PublicOnlyRoute', () => {
  it('shows the login page to signed-out visitors', () => {
    renderWithAuth(<AppRoutes />, { initialEntries: ['/login'] });

    expect(screen.getByText('Login page')).toBeInTheDocument();
  });

  it('returns a signed-in user to the page they originally asked for', () => {
    renderWithAuth(<AppRoutes />, {
      auth: { status: 'authenticated', user: CUSTOMER },
      initialEntries: [{ pathname: '/login', state: { from: { pathname: '/tickets' } } }],
    });

    expect(screen.getByText('Tickets page')).toBeInTheDocument();
  });

  it('sends a signed-in user home by default', () => {
    renderWithAuth(<AppRoutes />, {
      auth: { status: 'authenticated', user: CUSTOMER },
      initialEntries: ['/login'],
    });

    expect(screen.getByText('Dashboard page')).toBeInTheDocument();
  });
});
