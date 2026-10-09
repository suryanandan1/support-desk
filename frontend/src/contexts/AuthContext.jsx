import { createContext, useCallback, useEffect, useMemo, useState } from 'react';

import * as authApi from '../api/auth.js';
import { SESSION_EXPIRED_EVENT } from '../api/client.js';
import { clearToken, getToken, setToken } from '../utils/tokenStorage.js';

export const AuthContext = createContext(null);

/**
 * Holds the signed-in user for the whole app.
 *
 * status:
 *   'loading'        a saved token is being checked against /auth/me
 *   'authenticated'  user is set
 *   'anonymous'      nobody is signed in
 *   'error'          the server could not be reached to check the saved token
 */
export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [status, setStatus] = useState(() => (getToken() ? 'loading' : 'anonymous'));
  const [sessionExpired, setSessionExpired] = useState(false);

  // On page load (or after "Retry"), confirm the saved token is still valid.
  useEffect(() => {
    if (status !== 'loading') return undefined;
    let cancelled = false;
    authApi
      .fetchCurrentUser()
      .then((currentUser) => {
        if (cancelled) return;
        setUser(currentUser);
        setStatus('authenticated');
      })
      .catch((error) => {
        if (cancelled) return;
        if (error.response?.status === 401) {
          // The saved token is no longer accepted (expired, revoked, deactivated).
          clearToken();
          setUser(null);
          setSessionExpired(true);
          setStatus('anonymous');
        } else {
          // Server unreachable: keep the token so "Retry" can still succeed.
          setStatus('error');
        }
      });
    return () => {
      cancelled = true;
    };
  }, [status]);

  useEffect(() => {
    const handleExpired = () => {
      setUser(null);
      setStatus('anonymous');
      setSessionExpired(true);
    };
    window.addEventListener(SESSION_EXPIRED_EVENT, handleExpired);
    return () => window.removeEventListener(SESSION_EXPIRED_EVENT, handleExpired);
  }, []);

  const startSession = useCallback((tokenResponse) => {
    setToken(tokenResponse.access_token);
    setUser(tokenResponse.user);
    setSessionExpired(false);
    setStatus('authenticated');
    return tokenResponse.user;
  }, []);

  const login = useCallback(
    async (email, password) => startSession(await authApi.login(email, password)),
    [startSession],
  );

  const register = useCallback(
    async (details) => startSession(await authApi.register(details)),
    [startSession],
  );

  const logout = useCallback(() => {
    clearToken();
    setUser(null);
    setSessionExpired(false);
    setStatus('anonymous');
  }, []);

  const retry = useCallback(() => setStatus('loading'), []);

  const value = useMemo(
    () => ({ user, status, sessionExpired, login, register, logout, retry }),
    [user, status, sessionExpired, login, register, logout, retry],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
