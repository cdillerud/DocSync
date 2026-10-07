import { createContext, useContext, useState } from 'react';
import { login as apiLogin, entraLogin as apiEntraLogin } from '../lib/api';
import { entraAuthEnabled, entraLogin, entraLogout } from '../lib/entraAuth';

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(() => {
    const stored = localStorage.getItem('gpi_user');
    return stored ? JSON.parse(stored) : null;
  });
  const [token, setToken] = useState(() => localStorage.getItem('gpi_token'));

  const loginFn = async (username, password) => {
    // Microsoft sign-in when no password was typed (the Microsoft button);
    // the shared password login stays available as a fallback.
    if (entraAuthEnabled() && !username && !password) {
      const r = await entraLogin();
      if (!r?.idToken) {
        throw new Error('Microsoft sign-in cancelled');
      }
      const res = await apiEntraLogin(r.idToken);
      const { token: t, user: u } = res.data;
      localStorage.setItem('gpi_token', t);
      localStorage.setItem('gpi_user', JSON.stringify(u));
      setToken(t);
      setUser(u);
      return u;
    }
    const res = await apiLogin(username, password);
    const { token: t, user: u } = res.data;
    localStorage.setItem('gpi_token', t);
    localStorage.setItem('gpi_user', JSON.stringify(u));
    setToken(t);
    setUser(u);
    return u;
  };

  const logout = async () => {
    localStorage.removeItem('gpi_token');
    localStorage.removeItem('gpi_user');
    if (entraAuthEnabled()) {
      try { await entraLogout(); } catch { /* popup blocked: Hub session is already cleared */ }
    }
    setToken(null);
    setUser(null);
  };

  const isAuthenticated = !!token && !!user;

  return (
    <AuthContext.Provider value={{ user, token, login: loginFn, logout, isAuthenticated }}>
      {children}
    </AuthContext.Provider>
  );
}

export const useAuth = () => useContext(AuthContext);
