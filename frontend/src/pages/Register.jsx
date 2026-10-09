import Alert from '@mui/material/Alert';
import Button from '@mui/material/Button';
import Link from '@mui/material/Link';
import Stack from '@mui/material/Stack';
import TextField from '@mui/material/TextField';
import Typography from '@mui/material/Typography';
import { useState } from 'react';
import { Link as RouterLink } from 'react-router';

import PasswordField from '../components/PasswordField.jsx';
import useAuth from '../hooks/useAuth.js';
import { getErrorCode, getErrorMessage, getFieldErrors } from '../utils/errors.js';
import {
  hasErrors,
  PASSWORD_MIN_LENGTH,
  validateEmail,
  validateFullName,
  validatePassword,
} from '../utils/validation.js';

const EMPTY_FORM = { fullName: '', email: '', password: '', confirmPassword: '' };

// API field names -> form field names, for server-side validation messages.
const API_FIELDS = { full_name: 'fullName', email: 'email', password: 'password' };

function validate(values) {
  return {
    fullName: validateFullName(values.fullName),
    email: validateEmail(values.email),
    password: validatePassword(values.password),
    confirmPassword:
      values.confirmPassword === values.password ? '' : 'Passwords do not match',
  };
}

export default function Register() {
  const { register } = useAuth();
  const [values, setValues] = useState(EMPTY_FORM);
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
    const errors = validate(values);
    setFieldErrors(errors);
    if (hasErrors(errors)) return;

    setSubmitting(true);
    setFormError('');
    try {
      await register({
        fullName: values.fullName.trim(),
        email: values.email.trim(),
        password: values.password,
      });
    } catch (error) {
      if (getErrorCode(error) === 'conflict') {
        setFieldErrors({ email: getErrorMessage(error) });
      } else {
        const serverErrors = getFieldErrors(error);
        const mapped = Object.fromEntries(
          Object.entries(serverErrors)
            .filter(([field]) => API_FIELDS[field])
            .map(([field, message]) => [API_FIELDS[field], message]),
        );
        setFieldErrors(mapped);
        if (!hasErrors(mapped)) setFormError(getErrorMessage(error));
      }
      setSubmitting(false);
    }
  }

  return (
    <Stack component="form" spacing={2.5} noValidate onSubmit={handleSubmit}>
      <div>
        <Typography variant="h5" component="h1">
          Create your account
        </Typography>
        <Typography color="text.secondary">Get answers and track your support requests.</Typography>
      </div>

      {formError && <Alert severity="error">{formError}</Alert>}

      <TextField
        label="Full name"
        name="fullName"
        autoComplete="name"
        autoFocus
        fullWidth
        value={values.fullName}
        onChange={handleChange}
        error={Boolean(fieldErrors.fullName)}
        helperText={fieldErrors.fullName}
      />
      <TextField
        label="Email"
        name="email"
        type="email"
        autoComplete="email"
        fullWidth
        value={values.email}
        onChange={handleChange}
        error={Boolean(fieldErrors.email)}
        helperText={fieldErrors.email}
      />
      <PasswordField
        label="Password"
        name="password"
        autoComplete="new-password"
        fullWidth
        value={values.password}
        onChange={handleChange}
        error={Boolean(fieldErrors.password)}
        helperText={
          fieldErrors.password ||
          `At least ${PASSWORD_MIN_LENGTH} characters, with a letter and a number.`
        }
      />
      <PasswordField
        label="Confirm password"
        name="confirmPassword"
        autoComplete="new-password"
        fullWidth
        value={values.confirmPassword}
        onChange={handleChange}
        error={Boolean(fieldErrors.confirmPassword)}
        helperText={fieldErrors.confirmPassword}
      />

      <Button type="submit" variant="contained" size="large" loading={submitting} fullWidth>
        Create account
      </Button>

      <Typography variant="body2" sx={{ textAlign: 'center' }}>
        Already have an account?{' '}
        <Link component={RouterLink} to="/login">
          Sign in
        </Link>
      </Typography>
    </Stack>
  );
}
