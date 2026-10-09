// Helpers for the API's error envelope: { "error": { code, message, details? } }.

/** A sentence a user can act on, for any error thrown by an API call. */
export function getErrorMessage(error, fallback = 'Something went wrong. Please try again.') {
  if (!error?.response) {
    if (error?.code === 'ECONNABORTED') {
      return 'The server took too long to respond. Please try again.';
    }
    return 'Cannot reach the server. Check your connection and try again.';
  }
  return error.response.data?.error?.message || fallback;
}

/**
 * Per-field messages from a 422 validation error, keyed by the API's field name,
 * e.g. { email: "value is not a valid email address" }. Empty for other errors.
 */
export function getFieldErrors(error) {
  const details = error?.response?.data?.error?.details;
  if (!Array.isArray(details)) {
    return {};
  }
  const fieldErrors = {};
  for (const detail of details) {
    if (detail.field && !fieldErrors[detail.field]) {
      fieldErrors[detail.field] = detail.message;
    }
  }
  return fieldErrors;
}

export function getErrorCode(error) {
  return error?.response?.data?.error?.code ?? null;
}
