import { createContext, useContext, useState, useEffect } from 'react';
import { login as apiLogin } from '../lib/api';

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(() => {
    const stored = localStorage.getItem('gpi_user');
    return stored ? JSON.parse(stored) : null;
  });
  const [token, setToken] = useState(() => localStorage.getItem('gpi_token'));

  const loginFn = async (username, password) => {
    const res = await apiLogin(username, password);
    const { token: t, user: u } = res.data;
    localStorage.setItem('gpi_token', t);
    localStorage.setItem('gpi_user', JSON.stringify(u));
    setToken(t);
    setUser(u);
    return u;
  };

  const logout = () => {
    localStorage.removeItem('gpi_token');
    localStorage.removeItem('gpi_user');
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
