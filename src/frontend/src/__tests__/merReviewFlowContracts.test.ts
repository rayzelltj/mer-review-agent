import { beforeEach, describe, expect, it } from "vitest";

import {
  getDefaultReviewPeriodEnd,
  getStoredReviewClientId,
  getStoredReviewPeriodEnd,
  setStoredReviewClientId,
  setStoredReviewPeriodEnd,
} from "@/services/QboReviewContextService";
import { buildMerReviewPrompt } from "@/utils/merReviewPrompt";

describe("buildMerReviewPrompt", () => {
  it("always encodes client and period contract", () => {
    const prompt = buildMerReviewPrompt("acme_co", "2025-12-31");
    expect(prompt).toBe(
      "Run a balance sheet review for client acme_co for period end 2025-12-31."
    );
  });

  it("appends optional reviewer notes without losing the contract prefix", () => {
    const prompt = buildMerReviewPrompt(
      "acme_co",
      "2025-12-31",
      "Focus on cash and AP variances."
    );
    expect(prompt).toContain(
      "Run a balance sheet review for client acme_co for period end 2025-12-31."
    );
    expect(prompt).toContain("Reviewer request: Focus on cash and AP variances.");
  });
});

describe("QboReviewContextService", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it("persists and normalizes the selected client id", () => {
    setStoredReviewClientId("  blackbird_fabrics  ");
    expect(getStoredReviewClientId()).toBe("blackbird_fabrics");
  });

  it("returns default period end when nothing is stored", () => {
    expect(getStoredReviewPeriodEnd()).toBe(getDefaultReviewPeriodEnd());
  });

  it("stores valid period_end and ignores invalid values", () => {
    setStoredReviewPeriodEnd("2025-12-31");
    expect(getStoredReviewPeriodEnd()).toBe("2025-12-31");

    setStoredReviewPeriodEnd("12/31/2025");
    expect(getStoredReviewPeriodEnd()).toBe("2025-12-31");
  });
});
