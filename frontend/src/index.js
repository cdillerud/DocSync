import React from "react";
import ReactDOM from "react-dom/client";
import { MsalProvider } from "@azure/msal-react";
import "@/index.css";
import App from "@/App";
import TodayIntakeDrilldown from "@/components/TodayIntakeDrilldown";
import { getMsalInstance } from "@/lib/msalConfig";

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

const root = ReactDOM.createRoot(document.getElementById("root"));
root.render(<React.StrictMode>{tree}</React.StrictMode>);
