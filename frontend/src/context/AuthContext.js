import { createContext, useContext, useEffect, useState } from 'react';
import { login as apiLogin } from '../lib/api';
import {
  accountToLegacyUser,
  entraAuthEnabled,
  entraLogin,
  entraLogout,
  getActiveEntraAccount,
} from '../lib/entraAuth';

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(() => {
    const stored = localStorage.getItem('gpi_user');
    return stored ? JSON.parse(stored) : null;
  });
  const [token, setToken] = useState(() => localStorage.getItem('gpi_token'));

  // On mount: when Entra is enabled, hydrate the user from the active MSAL
  // account if one already exists (e.g. after page refresh within session).
  useEffect(() => {
    if (!entraAuthEnabled()) return;
    const account = getActiveEntraAccount();
    if (account) {
      const u = accountToLegacyUser(account);
      if (u) {
        localStorage.setItem('gpi_user', JSON.stringify(u));
        setUser(u);
        // We deliberately do NOT mirror the access token into React state —
        // the axios interceptor pulls a fresh one per request.
        setToken('entra'); // sentinel: non-empty truthy value gates isAuthenticated
      }
    }
  }, []);

  const loginFn = async (username, password) => {
    if (entraAuthEnabled()) {
      const account = await entraLogin();
      if (!account) {
        throw new Error('Entra sign-in cancelled');
      }
      const u = accountToLegacyUser(account);
      localStorage.setItem('gpi_user', JSON.stringify(u));
      setUser(u);
      setToken('entra');
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
    if (entraAuthEnabled()) {
      await entraLogout();
    } else {
      localStorage.removeItem('gpi_token');
      localStorage.removeItem('gpi_user');
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
