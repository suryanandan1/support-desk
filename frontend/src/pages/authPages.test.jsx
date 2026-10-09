import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { apiError, networkError, renderWithAuth } from '../test/renderWithAuth.jsx';
import Login from './Login.jsx';
import Register from './Register.jsx';

async function fillLogin(email, password) {
  if (email) await userEvent.type(screen.getByLabelText('Email'), email);
  if (password) await userEvent.type(screen.getByLabelText('Password'), password);
  await userEvent.click(screen.getByRole('button', { name: 'Sign in' }));
}

describe('Login page', () => {
  it('validates fields before calling the API', async () => {
    const { auth } = renderWithAuth(<Login />);

    await fillLogin('', '');

    expect(screen.getByText('Email is required')).toBeInTheDocument();
    expect(screen.getByText('Password is required')).toBeInTheDocument();
    expect(auth.login).not.toHaveBeenCalled();
  });

  it('rejects a malformed email', async () => {
    const { auth } = renderWithAuth(<Login />);

    await fillLogin('not-an-email', 'Password123');

    expect(screen.getByText('Enter a valid email address')).toBeInTheDocument();
    expect(auth.login).not.toHaveBeenCalled();
  });

  it('signs in with the trimmed email', async () => {
    const login = vi.fn().mockResolvedValue({});
    renderWithAuth(<Login />, { auth: { login } });

    await fillLogin('  casey@example.com  ', 'Password123');

    expect(login).toHaveBeenCalledWith('casey@example.com', 'Password123');
  });

  it('shows the API error message when sign-in fails', async () => {
    const login = vi
      .fn()
      .mockRejectedValue(
        apiError(401, { code: 'not_authenticated', message: 'Incorrect email or password' }),
      );
    renderWithAuth(<Login />, { auth: { login } });

    await fillLogin('casey@example.com', 'WrongPass1');

    expect(await screen.findByRole('alert')).toHaveTextContent('Incorrect email or password');
    expect(screen.getByRole('button', { name: 'Sign in' })).toBeEnabled();
  });

  it('explains when the server is unreachable', async () => {
    const login = vi.fn().mockRejectedValue(networkError());
    renderWithAuth(<Login />, { auth: { login } });

    await fillLogin('casey@example.com', 'Password123');

    expect(await screen.findByRole('alert')).toHaveTextContent(/cannot reach the server/i);
  });

  it('tells the user when their session ended', () => {
    renderWithAuth(<Login />, { auth: { sessionExpired: true } });

    expect(screen.getByText(/your session has ended/i)).toBeInTheDocument();
  });

  it('can reveal the typed password', async () => {
    renderWithAuth(<Login />);
    const password = screen.getByLabelText('Password');
    expect(password).toHaveAttribute('type', 'password');

    await userEvent.click(screen.getByRole('button', { name: 'Show password' }));

    expect(password).toHaveAttribute('type', 'text');
  });
});

async function fillRegister({ fullName, email, password, confirm }) {
  if (fullName) await userEvent.type(screen.getByLabelText('Full name'), fullName);
  if (email) await userEvent.type(screen.getByLabelText('Email'), email);
  if (password) await userEvent.type(screen.getByLabelText('Password'), password);
  if (confirm) await userEvent.type(screen.getByLabelText('Confirm password'), confirm);
  await userEvent.click(screen.getByRole('button', { name: 'Create account' }));
}

const VALID = {
  fullName: 'Casey Customer',
  email: 'casey@example.com',
  password: 'Password123',
  confirm: 'Password123',
};

describe('Register page', () => {
  it('requires matching passwords', async () => {
    const { auth } = renderWithAuth(<Register />);

    await fillRegister({ ...VALID, confirm: 'Password124' });

    expect(screen.getByText('Passwords do not match')).toBeInTheDocument();
    expect(auth.register).not.toHaveBeenCalled();
  });

  it('enforces the password rules before calling the API', async () => {
    const { auth } = renderWithAuth(<Register />);

    await fillRegister({ ...VALID, password: 'password', confirm: 'password' });

    expect(screen.getByText(/one letter and one number/)).toBeInTheDocument();
    expect(auth.register).not.toHaveBeenCalled();
  });

  it('submits the trimmed details', async () => {
    const register = vi.fn().mockResolvedValue({});
    renderWithAuth(<Register />, { auth: { register } });

    await fillRegister({ ...VALID, fullName: '  Casey Customer ' });

    expect(register).toHaveBeenCalledWith({
      fullName: 'Casey Customer',
      email: 'casey@example.com',
      password: 'Password123',
    });
  });

  it('shows a duplicate email next to the email field', async () => {
    const register = vi
      .fn()
      .mockRejectedValue(
        apiError(409, { code: 'conflict', message: 'An account with this email already exists' }),
      );
    renderWithAuth(<Register />, { auth: { register } });

    await fillRegister(VALID);

    expect(await screen.findByText('An account with this email already exists')).toBeInTheDocument();
    expect(screen.getByLabelText('Email')).toHaveAttribute('aria-invalid', 'true');
  });

  it('maps server-side validation errors onto the form fields', async () => {
    const register = vi.fn().mockRejectedValue(
      apiError(422, {
        code: 'validation_error',
        message: 'Request validation failed',
        details: [{ field: 'full_name', message: 'Full name cannot be blank' }],
      }),
    );
    renderWithAuth(<Register />, { auth: { register } });

    await fillRegister(VALID);

    expect(await screen.findByText('Full name cannot be blank')).toBeInTheDocument();
    expect(screen.getByLabelText('Full name')).toHaveAttribute('aria-invalid', 'true');
  });
});
