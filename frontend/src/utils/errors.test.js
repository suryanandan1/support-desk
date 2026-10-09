import { describe, expect, it } from 'vitest';

import { apiError, networkError } from '../test/renderWithAuth.jsx';
import { getErrorCode, getErrorMessage, getFieldErrors } from './errors.js';

describe('getErrorMessage', () => {
  it('uses the message from the API error envelope', () => {
    const error = apiError(401, { code: 'not_authenticated', message: 'Incorrect email or password' });

    expect(getErrorMessage(error)).toBe('Incorrect email or password');
  });

  it('explains when the server cannot be reached', () => {
    expect(getErrorMessage(networkError())).toMatch(/cannot reach the server/i);
  });

  it('explains timeouts', () => {
    const timeout = Object.assign(new Error('timeout'), { code: 'ECONNABORTED' });

    expect(getErrorMessage(timeout)).toMatch(/too long/i);
  });

  it('falls back when the response has no envelope', () => {
    const error = Object.assign(new Error('boom'), { response: { status: 502, data: '<html>' } });

    expect(getErrorMessage(error, 'Fallback')).toBe('Fallback');
  });
});

describe('getFieldErrors', () => {
  it('maps validation details by field, keeping the first message per field', () => {
    const error = apiError(422, {
      code: 'validation_error',
      message: 'Request validation failed',
      details: [
        { field: 'email', message: 'not a valid email' },
        { field: 'email', message: 'second message' },
        { field: 'password', message: 'too short' },
        { field: null, message: 'body-level problem' },
      ],
    });

    expect(getFieldErrors(error)).toEqual({ email: 'not a valid email', password: 'too short' });
    expect(getErrorCode(error)).toBe('validation_error');
  });

  it('returns an empty object for non-validation errors', () => {
    expect(getFieldErrors(networkError())).toEqual({});
    expect(getErrorCode(networkError())).toBeNull();
  });
});
