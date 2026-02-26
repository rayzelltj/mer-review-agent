import { APIClientError } from "@/api/apiClient";

const AUTH_SESSION_HINTS = [
  "no user found",
  "signature has expired",
  "invalid or expired",
  "expired authentication token",
  "unauthorized",
];

const getErrorMessage = (error: unknown): string => {
  if (error instanceof APIClientError) {
    const detail =
      (typeof error.data === "object" && error.data
        ? ((error.data as Record<string, unknown>).detail as string | undefined)
        : undefined) || "";
    return `${error.message || ""} ${detail} ${error.rawBody || ""}`.trim();
  }
  if (error instanceof Error) {
    return error.message || "";
  }
  return String(error || "");
};

export const buildAadLoginUrl = (postLoginRedirect?: string): string => {
  const requestedPath = String(postLoginRedirect || "").trim();
  const fallbackPath = `${window.location.pathname}${window.location.search || ""}` || "/";
  const redirectTarget = requestedPath || fallbackPath || "/";
  return `/.auth/login/aad?post_login_redirect_uri=${encodeURIComponent(redirectTarget)}`;
};

export const redirectToAadLogin = (postLoginRedirect?: string): void => {
  window.location.assign(buildAadLoginUrl(postLoginRedirect));
};

export const isAuthSessionError = (error: unknown): boolean => {
  const message = getErrorMessage(error).toLowerCase();
  const hasAuthHint = AUTH_SESSION_HINTS.some((hint) => message.includes(hint));
  if (error instanceof APIClientError) {
    if (error.status === 401) {
      return true;
    }
    if (error.status === 400 && hasAuthHint) {
      return true;
    }
  }
  return hasAuthHint;
};
