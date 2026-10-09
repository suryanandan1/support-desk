import Alert from '@mui/material/Alert';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import Link from '@mui/material/Link';
import Stack from '@mui/material/Stack';
import TextField from '@mui/material/TextField';
import Typography from '@mui/material/Typography';
import { useState } from 'react';
import { Link as RouterLink } from 'react-router';

import PasswordField from '../components/PasswordField.jsx';
import useAuth from '../hooks/useAuth.js';
import { getErrorMessage } from '../utils/errors.js';
import { hasErrors, validateEmail } from '../utils/validation.js';

export default function Login() {
  const { login, sessionExpired } = useAuth();
  const [values, setValues] = useState({ email: '', password: '' });
  const [fieldErrors, setFieldErrors] = useState({});
  const [formError, setFormError] = useState('');
  const [submitting, setSubmitting] = useState(false);

  function handleChange(event) {
    const { name, value } = event.target;
    setValues((current) => ({ ...current, [name]: value }));
    setFieldErrors((current) => ({ ...current, [name]: '' }));
  }

  async function handleSubmit(event) {
    event.preventDefault();
    const errors = {
      email: validateEmail(values.email),
      password: values.password ? '' : 'Password is required',
    };
    setFieldErrors(errors);
    if (hasErrors(errors)) return;

    setSubmitting(true);
    setFormError('');
    try {
      // On success the route guard redirects, so there is nothing else to do here.
      await login(values.email.trim(), values.password);
    } catch (error) {
      setFormError(getErrorMessage(error));
      setSubmitting(false);
    }
  }

  return (
    <Stack component="form" spacing={2.5} noValidate onSubmit={handleSubmit}>
      <div>
        <Typography variant="h5" component="h1">
          Sign in
        </Typography>
        <Typography color="text.secondary">Welcome back to the support portal.</Typography>
      </div>

      {sessionExpired && !formError && (
        <Alert severity="info">Your session has ended. Please sign in again.</Alert>
      )}
      {formError && <Alert severity="error">{formError}</Alert>}

      <TextField
        label="Email"
        name="email"
        type="email"
        autoComplete="email"
        autoFocus
        fullWidth
        value={values.email}
        onChange={handleChange}
        error={Boolean(fieldErrors.email)}
        helperText={fieldErrors.email}
      />
      <PasswordField
        label="Password"
        name="password"
        autoComplete="current-password"
        fullWidth
        value={values.password}
        onChange={handleChange}
        error={Boolean(fieldErrors.password)}
        helperText={fieldErrors.password}
      />

      <Button type="submit" variant="contained" size="large" loading={submitting} fullWidth>
        Sign in
      </Button>

      <Typography variant="body2" sx={{ textAlign: 'center' }}>
        New here?{' '}
        <Link component={RouterLink} to="/register">
          Create an account
        </Link>
      </Typography>

      {/* Development builds only: a plain note (not an alert, so screen readers don't
          announce it as urgent). */}
      {import.meta.env.DEV && (
        <Box
          component="aside"
          aria-label="Demo accounts"
          sx={{ border: 1, borderColor: 'divider', borderRadius: 2, px: 2, py: 1.5 }}
        >
          <Typography variant="caption" component="p" color="text.secondary">
            Demo accounts (created by <code>python scripts/seed.py</code>):
            <br />
            admin@example.com, agent@example.com, customer@example.com
            <br />
            Password: ChangeMe123!
          </Typography>
        </Box>
      )}
    </Stack>
  );
}
