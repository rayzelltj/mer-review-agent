export const buildMerReviewPrompt = (
  clientId: string,
  periodEnd: string,
  reviewerRequest?: string | null
): string => {
  const normalizedClientId = String(clientId || "").trim();
  const normalizedPeriodEnd = String(periodEnd || "").trim();
  const base = `Run a balance sheet review for client ${normalizedClientId} for period end ${normalizedPeriodEnd}.`;
  const notes = String(reviewerRequest || "").trim();
  if (!notes) {
    return base;
  }
  return `${base} Reviewer request: ${notes}`;
};
