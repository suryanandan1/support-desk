import axios from 'axios';

import { clearToken, getToken } from '../utils/tokenStorage.js';

export const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://127.0.0.1:8000/api/v1';

// Dispatched on window when the API rejects our token, so AuthContext can sign out.
export const SESSION_EXPIRED_EVENT = 'auth:session-expired';

const apiClient = axios.create({
  baseURL: API_BASE_URL,
  timeout: 20000,
});

apiClient.interceptors.request.use((config) => {
  const token = getToken();
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    // A 401 on a request that carried a token means the session is over (expired,
    // revoked, or the account was deactivated). A 401 from the login form itself has
    // no token attached and is just a wrong password.
    if (error.response?.status === 401 && error.config?.headers?.Authorization) {
      clearToken();
      window.dispatchEvent(new Event(SESSION_EXPIRED_EVENT));
    }
    return Promise.reject(error);
  },
);

export default apiClient;
