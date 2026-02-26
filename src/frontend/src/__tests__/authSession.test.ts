import { describe, expect, it } from "vitest";

import { APIClientError } from "@/api/apiClient";
import { buildAadLoginUrl, isAuthSessionError } from "@/utils/authSession";

describe("authSession", () => {
  it("builds login URL from explicit redirect path", () => {
    expect(buildAadLoginUrl("/plan/123?foo=bar")).toBe(
      "/.auth/login/aad?post_login_redirect_uri=%2Fplan%2F123%3Ffoo%3Dbar"
    );
  });

  it("detects 401 API responses as auth session errors", () => {
    const error = new APIClientError("unauthorized", 401, null, "");
    expect(isAuthSessionError(error)).toBe(true);
  });

  it("detects 400 no-user responses as auth session errors", () => {
    const error = new APIClientError("no user found", 400, { detail: "no user found" }, "");
    expect(isAuthSessionError(error)).toBe(true);
  });

  it("does not classify unrelated 400 responses as auth session errors", () => {
    const error = new APIClientError("Plan does not belong to this user", 400, null, "");
    expect(isAuthSessionError(error)).toBe(false);
  });
});
