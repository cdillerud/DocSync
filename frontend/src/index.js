import React from "react";
import ReactDOM from "react-dom/client";
import { MsalProvider } from "@azure/msal-react";
import "@/index.css";
import App from "@/App";
import TodayIntakeDrilldown from "@/components/TodayIntakeDrilldown";
import { getMsalInstance } from "@/lib/msalConfig";
import { installFetchAuthGuard } from "@/lib/fetchAuthGuard";

installFetchAuthGuard();

// Lazy-init: only construct MsalProvider when the environment can safely
// host MSAL (HTTPS or loopback + flag on). On insecure HTTP origins or with
// the flag off, we render <App/> directly so the legacy login keeps working.
const msalInstance = getMsalInstance();

const appTree = (
  <>
    <App />
    <TodayIntakeDrilldown />
  </>
);

const tree = msalInstance ? (
  <MsalProvider instance={msalInstance}>
    {appTree}
  </MsalProvider>
) : (
  appTree
);

// MSAL v5 popup sign-in: Microsoft sends the popup back to this origin with
// the auth response (code / error) in the URL. That window must hand the
// response to the main window (redirect bridge) instead of starting the app,
// or the main window waits forever ("Signing in with Microsoft..." spinner).
const isMsalPopupResponse =
  typeof window !== "undefined" &&
  window.opener &&
  window.opener !== window &&
  /[#?&](code|error)=/.test(`${window.location.hash}${window.location.search}`);

if (isMsalPopupResponse) {
  import("@azure/msal-browser/redirect-bridge")
    .then((m) => m.broadcastResponseToMainFrame())
    .catch((e) => {
      // eslint-disable-next-line no-console
      console.error("[MSAL] could not return the sign-in response:", e);
    });
} else {
  const root = ReactDOM.createRoot(document.getElementById("root"));
  root.render(<React.StrictMode>{tree}</React.StrictMode>);
}
