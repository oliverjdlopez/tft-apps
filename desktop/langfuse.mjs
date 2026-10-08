/** Local Langfuse settings and authentication, used only by the main process. */
import { readFileSync } from "node:fs";
import path from "node:path";
import { parseEnv } from "node:util";

export const DEFAULT_LANGFUSE_URL = "http://localhost:15510/project/tft-apps-evals";

/** Reject destinations that must never receive the local bootstrap password. */
export function localLangfuseUrl(value) {
  const url = new URL(value);
  if (!["http:", "https:"].includes(url.protocol)
    || !["localhost", "127.0.0.1", "[::1]"].includes(url.hostname)
    || url.username || url.password || url.search || url.hash) {
    throw new Error("Langfuse desktop URL must be a local HTTP(S) URL without credentials, query, or fragment.");
  }
  return url.href;
}

/** Read the existing ignored env file, including from a Windows shell over WSL. */
export function readLangfuseSettings(root, {
  wsl, platform = process.platform, read = readFileSync, warn = console.warn,
} = {}) {
  const paths = platform === "win32" ? path.win32 : path.posix;
  const checkout = platform === "win32" && wsl
    ? paths.join("\\\\wsl.localhost", wsl.distro, root.replaceAll("/", "\\")) : root;
  let values;
  try { values = parseEnv(read(paths.join(checkout, "tft-chat", "evals", "langfuse", ".env"), "utf8")); }
  catch (error) {
    if (error.code !== "ENOENT") warn("[Langfuse] Could not read local sign-in settings; use the sign-in page.");
    return { url: DEFAULT_LANGFUSE_URL };
  }
  let url;
  try { url = localLangfuseUrl(values.LANGFUSE_DESKTOP_URL || DEFAULT_LANGFUSE_URL); }
  catch {
    warn("[Langfuse] Invalid LANGFUSE_DESKTOP_URL; automatic sign-in is disabled.");
    return { url: DEFAULT_LANGFUSE_URL };
  }
  return {
    url,
    ...(values.LANGFUSE_DESKTOP_AUTO_LOGIN === "false" ? {} : {
      email: values.LANGFUSE_INIT_USER_EMAIL,
      password: values.LANGFUSE_INIT_USER_PASSWORD,
    }),
  };
}

/** Establish cookies in the view's own Chromium session before loading its page. */
export async function signInLangfuse(partition, settings, {
  warn = console.warn, timeout = 15000,
} = {}) {
  if (!settings.email || !settings.password) return false;
  try {
    const url = localLangfuseUrl(settings.url);
    const signal = AbortSignal.timeout(timeout);
    const request = async (endpoint, options = {}) => {
      const response = await partition.fetch(new URL(endpoint, url).href, {
        ...options, credentials: "include", redirect: "error", signal,
      });
      if (!response.ok) throw new Error("Langfuse authentication request failed.");
      return response.json();
    };
    // Keep an existing login, including an account explicitly chosen by the user.
    if ((await request("/api/auth/session")).user) return true;
    const { csrfToken } = await request("/api/auth/csrf");
    if (typeof csrfToken !== "string" || !csrfToken) throw new Error("Missing CSRF token.");
    await request("/api/auth/callback/credentials", {
      method: "POST",
      headers: { "content-type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams({
        csrfToken, email: settings.email, password: settings.password,
        callbackUrl: url, json: "true",
      }).toString(),
    });
    const result = await request("/api/auth/session");
    if (result.user?.email?.toLowerCase() !== settings.email.toLowerCase()) throw new Error("Sign-in was not accepted.");
    await partition.cookies.flushStore();
    return true;
  } catch {
    // Never print request bodies, server errors, passwords, or session cookies.
    warn("[Langfuse] Automatic sign-in did not complete; use the sign-in page or retry the tab.");
    return false;
  }
}
