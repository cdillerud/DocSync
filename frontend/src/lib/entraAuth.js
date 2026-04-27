/**
 * P1.K — Entra ID auth helpers (token acquisition, login, logout).
 *
 * All helpers are no-ops when REACT_APP_ENTRA_AUTH_ENABLED !== 'true'.
 * Token acquisition: silent first, interactive popup fallback on
 * InteractionRequiredAuthError.
 */
import { InteractionRequiredAuthError } from '@azure/msal-browser';
import { msalInstance, loginRequest, entraAuthEnabled } from './msalConfig';

export { entraAuthEnabled };

let _initPromise = null;

/** MSAL v5 requires explicit initialize() before any other call. */
const ensureInitialized = () => {
  if (!_initPromise) {
    _initPromise = msalInstance.initialize();
  }
  return _initPromise;
};

export const getActiveEntraAccount = () => {
  if (!entraAuthEnabled()) return null;
  const active = msalInstance.getActiveAccount();
  if (active) return active;
  const accounts = msalInstance.getAllAccounts();
  if (accounts.length === 0) return null;
  msalInstance.setActiveAccount(accounts[0]);
  return accounts[0];
};

/**
 * Acquire a fresh access token for the configured API scope.
 * Returns null if Entra is disabled or no account is signed in.
 * Throws on hard interaction failures (caller should fall back to legacy auth).
 */
export const acquireEntraToken = async () => {
  if (!entraAuthEnabled()) return null;
  await ensureInitialized();

  const account = getActiveEntraAccount();
  if (!account) return null;

  try {
    const response = await msalInstance.acquireTokenSilent({
      ...loginRequest,
      account,
    });
    return response.accessToken;
  } catch (err) {
    if (err instanceof InteractionRequiredAuthError) {
      const response = await msalInstance.acquireTokenPopup({
        ...loginRequest,
        account,
      });
      return response.accessToken;
    }
    throw err;
  }
};

/**
 * Trigger interactive login via popup. Returns the parsed account
 * with idTokenClaims, or null if Entra is disabled.
 */
export const entraLogin = async () => {
  if (!entraAuthEnabled()) return null;
  await ensureInitialized();

  const result = await msalInstance.loginPopup(loginRequest);
  if (result?.account) {
    msalInstance.setActiveAccount(result.account);
  }
  return result?.account || null;
};

/**
 * Trigger interactive logout via popup. Always clears legacy localStorage too
 * so flag-on-then-off transitions cannot leave dangling auth state.
 */
export const entraLogout = async () => {
  try {
    if (entraAuthEnabled()) {
      await ensureInitialized();
      const account = getActiveEntraAccount();
      if (account) {
        await msalInstance.logoutPopup({ account });
      }
    }
  } finally {
    try {
      localStorage.removeItem('gpi_token');
      localStorage.removeItem('gpi_user');
    } catch {
      /* localStorage may be unavailable in some environments */
    }
  }
};

/**
 * Derive a legacy-shaped user object from an Entra account.
 * Used by AuthContext so all downstream UI keeps working unchanged.
 */
export const accountToLegacyUser = (account) => {
  if (!account) return null;
  const claims = account.idTokenClaims || {};
  const roles = Array.isArray(claims.roles) ? claims.roles : [];
  const email =
    claims.preferred_username || claims.email || account.username || '';
  return {
    id: claims.oid || account.localAccountId || account.homeAccountId,
    username: email,
    email,
    display_name: claims.name || account.name || email,
    role: roles[0] || 'viewer',
    roles,
    auth_source: 'entra',
  };
};
