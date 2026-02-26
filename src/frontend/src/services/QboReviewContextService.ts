const QBO_REVIEW_CLIENT_ID_KEY = "macae.mer_review.client_id";
const QBO_REVIEW_PERIOD_END_KEY = "macae.mer_review.period_end";

const safeWindow = (): Window | null => {
  if (typeof window === "undefined") {
    return null;
  }
  return window;
};

const formatDate = (value: Date): string => {
  const year = value.getFullYear();
  const month = String(value.getMonth() + 1).padStart(2, "0");
  const day = String(value.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
};

const normalizeClientId = (value: string | null | undefined): string =>
  String(value || "").trim();

const isIsoDate = (value: string): boolean => /^\d{4}-\d{2}-\d{2}$/.test(value);

export const getDefaultReviewPeriodEnd = (): string => {
  const now = new Date();
  // Default to last day of the previous month.
  return formatDate(new Date(now.getFullYear(), now.getMonth(), 0));
};

export const getStoredReviewClientId = (): string => {
  const win = safeWindow();
  if (!win || !win.localStorage) {
    return "";
  }
  try {
    return normalizeClientId(win.localStorage.getItem(QBO_REVIEW_CLIENT_ID_KEY));
  } catch {
    return "";
  }
};

export const setStoredReviewClientId = (clientId: string): void => {
  const win = safeWindow();
  if (!win || !win.localStorage) {
    return;
  }
  const normalized = normalizeClientId(clientId);
  try {
    if (!normalized) {
      win.localStorage.removeItem(QBO_REVIEW_CLIENT_ID_KEY);
      return;
    }
    win.localStorage.setItem(QBO_REVIEW_CLIENT_ID_KEY, normalized);
  } catch {
    // Ignore storage failures (private mode/quota).
  }
};

export const getStoredReviewPeriodEnd = (): string => {
  const fallback = getDefaultReviewPeriodEnd();
  const win = safeWindow();
  if (!win || !win.localStorage) {
    return fallback;
  }
  try {
    const raw = String(win.localStorage.getItem(QBO_REVIEW_PERIOD_END_KEY) || "").trim();
    return isIsoDate(raw) ? raw : fallback;
  } catch {
    return fallback;
  }
};

export const setStoredReviewPeriodEnd = (periodEnd: string): void => {
  const win = safeWindow();
  if (!win || !win.localStorage) {
    return;
  }
  const normalized = String(periodEnd || "").trim();
  try {
    if (!isIsoDate(normalized)) {
      return;
    }
    win.localStorage.setItem(QBO_REVIEW_PERIOD_END_KEY, normalized);
  } catch {
    // Ignore storage failures (private mode/quota).
  }
};
