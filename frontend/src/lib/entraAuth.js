/**
 * P1.K — Entra ID auth helpers (token acquisition, login, logout).
 *
 * All helpers short-circuit to a no-op when MSAL is not initialized (either
 * because REACT_APP_ENTRA_AUTH_ENABLED is false OR the origin is insecure).
 */
import { InteractionRequiredAuthError } from '@azure/msal-browser';
import { getMsalInstance, loginRequest, entraAuthEnabled } from './msalConfig';

export { entraAuthEnabled };

let _initPromise = null;

/** MSAL v5 requires explicit initialize() before any other call. */
const ensureInitialized = (instance) => {
  if (!_initPromise) {
    _initPromise = instance.initialize();
  }
  return _initPromise;
};

export const getActiveEntraAccount = () => {
  const instance = getMsalInstance();
  if (!instance) return null;
  const active = instance.getActiveAccount();
  if (active) return active;
  const accounts = instance.getAllAccounts();
  if (accounts.length === 0) return null;
  instance.setActiveAccount(accounts[0]);
  return accounts[0];
};

/**
 * Acquire a fresh access token for the configured API scope.
 * Returns null if Entra is disabled, the origin is insecure, or no account
 * is signed in. Throws on hard interaction failures.
 */
export const acquireEntraToken = async () => {
  const instance = getMsalInstance();
  if (!instance) return null;
  await ensureInitialized(instance);

  const account = getActiveEntraAccount();
  if (!account) return null;

  try {
    const response = await instance.acquireTokenSilent({
      ...loginRequest,
      account,
    });
    return response.accessToken;
  } catch (err) {
    if (err instanceof InteractionRequiredAuthError) {
      const response = await instance.acquireTokenPopup({
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
 * with idTokenClaims, or null if Entra is disabled / insecure context.
 */
export const entraLogin = async () => {
  const instance = getMsalInstance();
  if (!instance) return null;
  await ensureInitialized(instance);

  const result = await instance.loginPopup(loginRequest);
  if (result?.account) {
    instance.setActiveAccount(result.account);
  }
  return result?.account || null;
};

/**
 * Trigger interactive logout via popup. Always clears legacy localStorage too
 * so flag-on-then-off transitions cannot leave dangling auth state.
 */
export const entraLogout = async () => {
  try {
    const instance = getMsalInstance();
    if (instance) {
      await ensureInitialized(instance);
      const account = getActiveEntraAccount();
      if (account) {
        await instance.logoutPopup({ account });
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
