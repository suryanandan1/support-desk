// The access token lives in localStorage so a page reload keeps the user signed in.
// Every call is wrapped: storage can be unavailable (private mode, blocked site data),
// in which case the session simply lasts until the tab is closed.
const TOKEN_KEY = 'support.accessToken';

export function getToken() {
  try {
    return window.localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setToken(token) {
  try {
    window.localStorage.setItem(TOKEN_KEY, token);
  } catch {
    // Storage unavailable: nothing else to do.
  }
}

export function clearToken() {
  try {
    window.localStorage.removeItem(TOKEN_KEY);
  } catch {
    // Storage unavailable: nothing else to do.
  }
}
