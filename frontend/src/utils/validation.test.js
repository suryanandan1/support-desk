import { describe, expect, it } from 'vitest';

import { validateEmail, validateFullName, validatePassword } from './validation.js';

// These mirror the backend rules in app/schemas/auth.py.
describe('validatePassword', () => {
  it.each([
    ['', 'Password is required'],
    ['Short1', 'at least 8 characters'],
    ['onlyletters', 'one letter and one number'],
    ['12345678', 'one letter and one number'],
    [`A1${'x'.repeat(127)}`, 'at most 128 characters'],
  ])('rejects %j', (password, message) => {
    expect(validatePassword(password)).toContain(message);
  });

  it('accepts a password with a letter and a number', () => {
    expect(validatePassword('Password123')).toBe('');
  });
});

describe('validateEmail', () => {
  it.each(['', '   ', 'not-an-email', 'a@b', '@example.com', 'two@@example.com'])(
    'rejects %j',
    (email) => {
      expect(validateEmail(email)).not.toBe('');
    },
  );

  it('accepts a normal address, ignoring surrounding spaces', () => {
    expect(validateEmail('  casey@example.com ')).toBe('');
  });
});

describe('validateFullName', () => {
  it('requires a non-blank name', () => {
    expect(validateFullName('   ')).toBe('Full name is required');
  });

  it('limits the length to 120 characters', () => {
    expect(validateFullName('x'.repeat(121))).toContain('at most 120');
    expect(validateFullName('x'.repeat(120))).toBe('');
  });
});
