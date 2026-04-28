/**
 * P1.K — Microsoft Entra ID MSAL configuration (lazy, secure-context aware).
 *
 * Cache: sessionStorage (security over UX continuity per playbook §6).
 * Auth flow: OAuth 2.0 Authorization Code + PKCE (default for SPA in MSAL v5).
 *
 * Lazy-init contract (regression fix 2026-04-28):
 *  - PublicClientApplication is constructed ONLY when both:
 *      a) REACT_APP_ENTRA_AUTH_ENABLED === 'true'
 *      b) window.isSecureContext === true (HTTPS or loopback)
 *  - On insecure origins (e.g. http://<public-ip>) the singleton is null and
 *    every Entra helper short-circuits to legacy auth. This restores the
 *    pre-P1.K behavior of plain-HTTP test origins (white-screen regression).
 */
import { PublicClientApplication, LogLevel } from '@azure/msal-browser';

const TENANT_ID = process.env.REACT_APP_ENTRA_TENANT_ID || '';
const CLIENT_ID = process.env.REACT_APP_ENTRA_CLIENT_ID || '';
export const ENTRA_API_SCOPE = process.env.REACT_APP_ENTRA_API_SCOPE || '';

const flagOn = () =>
  String(process.env.REACT_APP_ENTRA_AUTH_ENABLED || 'false').toLowerCase() === 'true';

const secureContext = () =>
  typeof window !== 'undefined' && window.isSecureContext === true;

/**
 * True only when MSAL can SAFELY initialize in this environment.
 * Used by AuthContext / LoginPage / api interceptor to gate the Entra branch.
 */
export const entraAuthEnabled = () => flagOn() && secureContext();

export const msalConfig = {
  auth: {
    clientId: CLIENT_ID,
    authority: TENANT_ID ? `https://login.microsoftonline.com/${TENANT_ID}` : '',
    redirectUri: typeof window !== 'undefined' ? window.location.origin : '',
    postLogoutRedirectUri: typeof window !== 'undefined' ? window.location.origin : '',
    navigateToLoginRequestUrl: true,
  },
  cache: {
    cacheLocation: 'sessionStorage',
    storeAuthStateInCookie: false,
  },
  system: {
    loggerOptions: {
      loggerCallback: (level, message, containsPii) => {
        if (containsPii) return;
        if (level === LogLevel.Error) {
          // eslint-disable-next-line no-console
          console.error('[MSAL]', message);
        }
      },
      piiLoggingEnabled: false,
    },
  },
};

let _msalSingleton = null;

/**
 * Lazily construct and cache the PublicClientApplication.
 * Returns null when the environment cannot host MSAL safely (insecure
 * context or flag off). Callers MUST handle the null path.
 */
export const getMsalInstance = () => {
  if (!entraAuthEnabled()) return null;
  if (_msalSingleton) return _msalSingleton;
  try {
    _msalSingleton = new PublicClientApplication(msalConfig);
  } catch (err) {
    // eslint-disable-next-line no-console
    console.error('[MSAL] init failed; falling back to legacy auth:', err);
    _msalSingleton = null;
  }
  return _msalSingleton;
};

// Default scopes requested at login + token acquisition.
export const loginRequest = {
  scopes: ENTRA_API_SCOPE ? [ENTRA_API_SCOPE] : [],
};
