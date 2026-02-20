import React, { useCallback, useEffect, useState } from "react";
import {
  Body1,
  Button,
  Caption1,
  Spinner,
  Tag,
  makeStyles,
} from "@fluentui/react-components";
import { ArrowClockwiseRegular } from "@fluentui/react-icons";
import { getApiUrl, headerBuilder } from "@/api/config";

type EvidenceItem = {
  evidence_type?: string;
  source?: string;
  as_of_date?: string;
  statement_end_date?: string;
  amount?: string | number | null;
  uri?: string | null;
  meta?: Record<string, any>;
};

type RuleDetail = {
  key: string;
  message: string;
  values?: Record<string, any>;
};

type RuleHit = {
  rule_id: string;
  rule_title: string;
  status: string;
  severity?: string;
  summary?: string;
  human_action?: string;
  best_practices_reference?: string;
  sources?: string[];
  details?: RuleDetail[];
  evidence_used?: EvidenceItem[];
};

type BalanceSheetAccount = {
  account_ref: string;
  name: string;
  type?: string;
  subtype?: string;
  balance?: string | number | null;
};

type BalanceSheetView = {
  client_id: string;
  period_end: string;
  generated_at: string;
  currency?: string;
  status_palette?: Record<string, string>;
  accounts: Array<{
    account: BalanceSheetAccount;
    status: string;
    rule_hits: RuleHit[];
  }>;
  unmapped_findings?: RuleHit[];
};

type ReviewRun = {
  run_id?: string;
  status?: string;
  summary?: string | null;
  totals?: Record<string, number>;
  findings?: RuleHit[];
  balance_sheet_view?: BalanceSheetView | null;
};

const STATUS_ORDER: Record<string, number> = {
  FAIL: 50,
  NEEDS_REVIEW: 40,
  WARN: 30,
  PASS: 20,
  NOT_APPLICABLE: 10,
};

const DEFAULT_STATUS_PALETTE: Record<string, string> = {
  FAIL: "#D13438",
  NEEDS_REVIEW: "#005A9E",
  WARN: "#EAA300",
  PASS: "#107C10",
  NOT_APPLICABLE: "#605E5C",
};

const runCache = new Map<string, ReviewRun>();
const runInflight = new Map<string, Promise<ReviewRun>>();

const useStyles = makeStyles({
  panel: {
    marginTop: "12px",
    paddingTop: "12px",
    borderTop: "1px solid var(--colorNeutralStroke2)",
  },
  panelHeader: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    gap: "12px",
    marginBottom: "6px",
  },
  panelTitle: {
    fontSize: "14px",
    fontWeight: 600,
    color: "var(--colorNeutralForeground1)",
  },
  metaRow: {
    display: "flex",
    flexWrap: "wrap",
    gap: "12px",
    color: "var(--colorNeutralForeground2)",
  },
  totalsRow: {
    display: "flex",
    flexWrap: "wrap",
    gap: "8px",
    marginTop: "6px",
  },
  summaryText: {
    marginTop: "8px",
    color: "var(--colorNeutralForeground1)",
    fontSize: "13px",
  },
  section: {
    marginTop: "12px",
    padding: "10px 12px",
    borderRadius: "8px",
    backgroundColor: "var(--colorNeutralBackground2)",
    border: "1px solid var(--colorNeutralStroke2)",
  },
  sectionSummary: {
    cursor: "pointer",
    fontSize: "13px",
    fontWeight: 600,
    color: "var(--colorNeutralForeground1)",
    listStyle: "none",
  },
  tableWrapper: {
    width: "100%",
    overflowX: "auto",
    marginTop: "8px",
  },
  table: {
    width: "100%",
    borderCollapse: "collapse",
    minWidth: "560px",
  },
  th: {
    textAlign: "left",
    fontSize: "11px",
    color: "var(--colorNeutralForeground3)",
    padding: "6px 4px",
    borderBottom: "1px solid var(--colorNeutralStroke2)",
    fontWeight: 600,
  },
  td: {
    padding: "6px 4px",
    borderBottom: "1px solid var(--colorNeutralStroke2)",
    fontSize: "12px",
    color: "var(--colorNeutralForeground1)",
    verticalAlign: "top",
  },
  accountName: {
    fontWeight: 600,
  },
  accountMeta: {
    fontSize: "11px",
    color: "var(--colorNeutralForeground3)",
  },
  statusPill: {
    display: "inline-flex",
    alignItems: "center",
    gap: "6px",
    padding: "2px 8px",
    borderRadius: "999px",
    fontSize: "11px",
    fontWeight: 600,
    border: "1px solid var(--colorNeutralStroke2)",
    backgroundColor: "var(--colorNeutralBackground1)",
  },
  statusDot: {
    width: "6px",
    height: "6px",
    borderRadius: "50%",
  },
  ruleList: {
    display: "flex",
    flexDirection: "column",
    gap: "8px",
    marginTop: "8px",
  },
  ruleCard: {
    padding: "8px",
    borderRadius: "8px",
    backgroundColor: "var(--colorNeutralBackground1)",
    border: "1px solid var(--colorNeutralStroke2)",
  },
  ruleHeader: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    gap: "8px",
  },
  ruleTitle: {
    fontSize: "12px",
    fontWeight: 600,
    color: "var(--colorNeutralForeground1)",
  },
  ruleSummary: {
    fontSize: "12px",
    color: "var(--colorNeutralForeground2)",
    marginTop: "4px",
  },
  ruleAction: {
    fontSize: "12px",
    color: "var(--colorNeutralForeground2)",
    marginTop: "4px",
  },
  detailBlock: {
    marginTop: "6px",
    paddingTop: "6px",
    borderTop: "1px dashed var(--colorNeutralStroke2)",
  },
  kvGrid: {
    display: "grid",
    gridTemplateColumns: "minmax(120px, 160px) 1fr",
    gap: "4px 8px",
    fontSize: "11px",
    color: "var(--colorNeutralForeground2)",
  },
  kvKey: {
    fontWeight: 600,
    color: "var(--colorNeutralForeground2)",
  },
  kvValue: {
    wordBreak: "break-word",
  },
  emptyState: {
    fontSize: "12px",
    color: "var(--colorNeutralForeground2)",
    marginTop: "6px",
  },
  muted: {
    color: "var(--colorNeutralForeground3)",
  },
  link: {
    color: "var(--colorNeutralBrandForeground1)",
    textDecoration: "none",
  },
  footerRow: {
    marginTop: "8px",
    display: "flex",
    gap: "8px",
    alignItems: "center",
    flexWrap: "wrap",
  },
});

const formatValue = (value: any): string => {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
};

const formatCurrency = (value: any, currency?: string): string => {
  if (value === null || value === undefined || value === "") return "—";
  const num = Number(value);
  if (!Number.isFinite(num)) return String(value);
  try {
    return new Intl.NumberFormat("en-US", {
      style: "currency",
      currency: currency || "USD",
      maximumFractionDigits: 2,
    }).format(num);
  } catch {
    return String(value);
  }
};

const statusColor = (status: string, palette?: Record<string, string>): string => {
  if (palette && palette[status]) return palette[status];
  return DEFAULT_STATUS_PALETTE[status] || DEFAULT_STATUS_PALETTE.NOT_APPLICABLE;
};

const worstStatus = (statuses: string[]): string => {
  if (!statuses.length) return "NOT_APPLICABLE";
  return statuses.reduce((prev, curr) =>
    (STATUS_ORDER[curr] || 0) > (STATUS_ORDER[prev] || 0) ? curr : prev
  );
};

const sortFindings = (items: RuleHit[]): RuleHit[] => {
  return [...items].sort((a, b) => {
    const left = STATUS_ORDER[a.status] || 0;
    const right = STATUS_ORDER[b.status] || 0;
    if (left !== right) return right - left;
    return (a.rule_id || "").localeCompare(b.rule_id || "");
  });
};

async function fetchRun(runId: string, force: boolean): Promise<ReviewRun> {
  if (!force && runCache.has(runId)) {
    return runCache.get(runId) as ReviewRun;
  }
  if (!force && runInflight.has(runId)) {
    return runInflight.get(runId) as Promise<ReviewRun>;
  }

  const apiUrl = getApiUrl();
  if (!apiUrl) {
    throw new Error("API URL is not configured.");
  }

  const url = `${apiUrl}/reviews/balance-sheet/runs/${runId}`;
  const request = fetch(url, { headers: headerBuilder() })
    .then(async (response) => {
      if (!response.ok) {
        const text = await response.text();
        throw new Error(text || "Failed to fetch review.");
      }
      return response.json();
    })
    .then((payload) => {
      runCache.set(runId, payload);
      return payload;
    })
    .finally(() => {
      runInflight.delete(runId);
    });

  runInflight.set(runId, request);
  return request;
}

const BalanceSheetReviewPanel: React.FC<{ runId: string }> = ({ runId }) => {
  const styles = useStyles();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [run, setRun] = useState<ReviewRun | null>(null);

  const loadRun = useCallback(
    async (force: boolean) => {
      if (!runId) return;
      setLoading(true);
      setError(null);
      try {
        const payload = await fetchRun(runId, force);
        setRun(payload);
      } catch (err: any) {
        setError(err?.message || "Failed to load review data.");
      } finally {
        setLoading(false);
      }
    },
    [runId]
  );

  useEffect(() => {
    void loadRun(false);
  }, [loadRun]);

  const view = run?.balance_sheet_view || null;
  const findings = sortFindings(run?.findings || []);
  const totals = run?.totals || {};

  return (
    <div className={styles.panel}>
      <div className={styles.panelHeader}>
        <Body1 className={styles.panelTitle}>Balance Sheet Review</Body1>
        <Button
          appearance="subtle"
          size="small"
          icon={<ArrowClockwiseRegular />}
          onClick={() => loadRun(true)}
        >
          Refresh
        </Button>
      </div>

      {loading && (
        <div className={styles.footerRow}>
          <Spinner size="tiny" />
          <Caption1 className={styles.muted}>Loading review data...</Caption1>
        </div>
      )}

      {error && <Caption1 className={styles.emptyState}>{error}</Caption1>}

      {!loading && run && (
        <>
          <div className={styles.metaRow}>
            <Caption1>Run: {runId}</Caption1>
            {run.status && <Caption1>Status: {run.status}</Caption1>}
            {view?.period_end && <Caption1>Period end: {view.period_end}</Caption1>}
          </div>

          {Object.keys(totals).length > 0 && (
            <div className={styles.totalsRow}>
              {Object.entries(totals).map(([key, value]) => {
                const status = key.toUpperCase();
                const color = statusColor(status, view?.status_palette);
                return (
                  <Tag
                    key={key}
                    appearance="outline"
                    style={{ borderColor: color, color }}
                  >
                    {status}: {value}
                  </Tag>
                );
              })}
            </div>
          )}

          {run.summary && <div className={styles.summaryText}>{run.summary}</div>}

          <details className={styles.section} open={!!view}>
            <summary className={styles.sectionSummary}>Balance Sheet View</summary>
            {!view && (
              <Caption1 className={styles.emptyState}>
                balance_sheet_view is not available yet for this run.
              </Caption1>
            )}
            {view && (
              <div className={styles.tableWrapper}>
                <table className={styles.table}>
                  <thead>
                    <tr>
                      <th className={styles.th}>Account</th>
                      <th className={styles.th}>Balance</th>
                      <th className={styles.th}>Status</th>
                      <th className={styles.th}>Rule Hits</th>
                    </tr>
                  </thead>
                  <tbody>
                    {view.accounts.map((row) => {
                      const color = statusColor(row.status, view.status_palette);
                      return (
                        <tr key={row.account.account_ref}>
                          <td className={styles.td}>
                            <div className={styles.accountName}>
                              {row.account.name || row.account.account_ref}
                            </div>
                            {(row.account.type || row.account.subtype) && (
                              <div className={styles.accountMeta}>
                                {[row.account.type, row.account.subtype]
                                  .filter(Boolean)
                                  .join(" / ")}
                              </div>
                            )}
                          </td>
                          <td className={styles.td}>
                            {formatCurrency(row.account.balance, view.currency)}
                          </td>
                          <td className={styles.td}>
                            <span
                              className={styles.statusPill}
                              style={{ borderColor: color, color }}
                            >
                              <span
                                className={styles.statusDot}
                                style={{ backgroundColor: color }}
                              />
                              {row.status}
                            </span>
                          </td>
                          <td className={styles.td}>
                            {row.rule_hits?.length ? (
                              <details>
                                <summary className={styles.sectionSummary}>
                                  View rule hits ({row.rule_hits.length})
                                </summary>
                                <div className={styles.ruleList}>
                                  {row.rule_hits.map((hit) => (
                                    <RuleHitCard key={`${row.account.account_ref}-${hit.rule_id}`} hit={hit} />
                                  ))}
                                </div>
                              </details>
                            ) : (
                              <span className={styles.muted}>None</span>
                            )}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}

            {view?.unmapped_findings?.length ? (
              <div className={styles.ruleList}>
                <Caption1 className={styles.muted}>Unmapped findings</Caption1>
                {view.unmapped_findings.map((hit) => (
                  <RuleHitCard key={`unmapped-${hit.rule_id}`} hit={hit} />
                ))}
              </div>
            ) : null}
          </details>

          <details className={styles.section}>
            <summary className={styles.sectionSummary}>
              Findings ({findings.length})
            </summary>
            {findings.length === 0 && (
              <Caption1 className={styles.emptyState}>No findings reported.</Caption1>
            )}
            {findings.length > 0 && (
              <div className={styles.ruleList}>
                {findings.map((hit) => (
                  <RuleHitCard key={`finding-${hit.rule_id}`} hit={hit} />
                ))}
              </div>
            )}
          </details>
        </>
      )}
    </div>
  );
};

const RuleHitCard: React.FC<{ hit: RuleHit }> = ({ hit }) => {
  const styles = useStyles();
  const color = statusColor(hit.status, DEFAULT_STATUS_PALETTE);
  const details = hit.details || [];
  const evidence = hit.evidence_used || [];

  return (
    <div className={styles.ruleCard}>
      <div className={styles.ruleHeader}>
        <span className={styles.ruleTitle}>
          {hit.rule_id} — {hit.rule_title}
        </span>
        <span className={styles.statusPill} style={{ borderColor: color, color }}>
          <span className={styles.statusDot} style={{ backgroundColor: color }} />
          {hit.status}
        </span>
      </div>

      {hit.summary && <div className={styles.ruleSummary}>{hit.summary}</div>}
      {hit.human_action && (
        <div className={styles.ruleAction}>Action: {hit.human_action}</div>
      )}

      {details.length > 0 && (
        <div className={styles.detailBlock}>
          <Caption1 className={styles.muted}>Details</Caption1>
          {details.map((detail, index) => (
            <div key={`${hit.rule_id}-detail-${index}`} className={styles.detailBlock}>
              <div className={styles.ruleSummary}>{detail.message}</div>
              {detail.values && (
                <div className={styles.kvGrid}>
                  {Object.entries(detail.values).map(([key, value]) => (
                    <React.Fragment key={`${hit.rule_id}-${detail.key}-${key}`}>
                      <span className={styles.kvKey}>{key}</span>
                      <span className={styles.kvValue}>{formatValue(value)}</span>
                    </React.Fragment>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {evidence.length > 0 && (
        <div className={styles.detailBlock}>
          <Caption1 className={styles.muted}>Evidence</Caption1>
          <div className={styles.kvGrid}>
            {evidence.map((item, index) => (
              <React.Fragment key={`${hit.rule_id}-evidence-${index}`}>
                <span className={styles.kvKey}>{item.evidence_type || "evidence"}</span>
                <span className={styles.kvValue}>
                  {[item.source, formatValue(item.amount), item.as_of_date, item.uri]
                    .filter((v) => v && v !== "—")
                    .join(" · ")}
                </span>
              </React.Fragment>
            ))}
          </div>
        </div>
      )}
    </div>
  );
};

export default BalanceSheetReviewPanel;
