// Many pages call the API with a raw fetch() instead of the axios `api`
// client, so they miss its auth interceptors. Before this guard they relied on
// the access_token cookie alone, and when the session expired (8h) they kept
// polling and quietly rendered empty data on every 401. This patches
// window.fetch once so /api calls get the same treatment as `api`: attach the
// stored token, and on 401 clear the session and go to /login.
const LOGIN_PATH = "/login";

function requestUrl(input) {
  if (typeof input === "string") return input;
  if (input instanceof URL) return input.href;
  return input?.url || "";
}

function isApiCall(url) {
  try {
    const u = new URL(url, window.location.origin);
    return u.pathname.startsWith("/api/") && u.pathname !== "/api/auth/login";
  } catch {
    return false;
  }
}

export function installFetchAuthGuard() {
  if (window.__gpiFetchGuard) return;
  window.__gpiFetchGuard = true;
  const originalFetch = window.fetch.bind(window);
  let redirecting = false;

  window.fetch = async (input, init) => {
    const url = requestUrl(input);
    if (!isApiCall(url)) return originalFetch(input, init);

    const token = localStorage.getItem("gpi_token");
    if (token && !(input instanceof Request)) {
      const headers = new Headers(init?.headers || {});
      if (!headers.has("Authorization")) {
        headers.set("Authorization", `Bearer ${token}`);
        init = { ...init, headers };
      }
    }

    const response = await originalFetch(input, init);
    if (response.status === 401 && !redirecting && window.location.pathname !== LOGIN_PATH) {
      redirecting = true;
      localStorage.removeItem("gpi_token");
      localStorage.removeItem("gpi_user");
      window.location.href = LOGIN_PATH;
    }
    return response;
  };
}
