/**
 * P1.K — Microsoft Entra ID MSAL configuration.
 *
 * Cache: sessionStorage (security over UX continuity per playbook §6).
 * Auth flow: OAuth 2.0 Authorization Code + PKCE (default for SPA in MSAL v5).
 *
 * Frozen contract:
 *  - clientId, tenantId, scope come from REACT_APP_ENTRA_* env vars.
 *  - Authority is constructed from the tenant ID; never overridden in code.
 *  - Redirect URI defaults to window.location.origin (matches the SPA app
 *    registration's redirect URI exactly; do not append paths).
 */
import { PublicClientApplication, LogLevel } from '@azure/msal-browser';

const TENANT_ID = process.env.REACT_APP_ENTRA_TENANT_ID || '';
const CLIENT_ID = process.env.REACT_APP_ENTRA_CLIENT_ID || '';
export const ENTRA_API_SCOPE = process.env.REACT_APP_ENTRA_API_SCOPE || '';

export const entraAuthEnabled = () =>
  String(process.env.REACT_APP_ENTRA_AUTH_ENABLED || 'false').toLowerCase() === 'true';

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

// Singleton — created once at module load. MsalProvider expects a stable instance.
export const msalInstance = new PublicClientApplication(msalConfig);

// Default scopes requested at login + token acquisition.
export const loginRequest = {
  scopes: ENTRA_API_SCOPE ? [ENTRA_API_SCOPE] : [],
};
