import apiClient from './client.js';

export async function login(email, password) {
  const { data } = await apiClient.post('/auth/login', { email, password });
  return data;
}

export async function register({ fullName, email, password }) {
  const { data } = await apiClient.post('/auth/register', {
    full_name: fullName,
    email,
    password,
  });
  return data;
}

export async function fetchCurrentUser() {
  const { data } = await apiClient.get('/auth/me');
  return data;
}
