# Known Gaps & Roadmap — MER Review Agent

> **Status:** Living document
> **Last updated:** 2025-02-20
> **See also:** [docs/rules/STATUS.md](../rules/STATUS.md), [docs/architecture/mer-review-agent-spec.md](../architecture/mer-review-agent-spec.md)

---

## Known Limitations

### Code-Level Gaps

| # | Gap | Impact | Component | Source |
|---|---|---|---|---|
| 1 | **No real bank statement parsing** | Evidence-dependent rules fall back to NEEDS_REVIEW for real data | Adapters | `docs/rules/STATUS.md` §4 |
| 2 | **No real petty cash document parsing** | Petty cash match uses mock data | Adapters | `docs/rules/STATUS.md` §4 |
| 3 | **No P&L rules** (MVP3) | Only balance sheet review, no income statement analysis | Rules | `mer-review-agent-spec.md` §4 |
| 4 | **Google Drive full integration** (MVP2) | Drive evidence rules auto-disable; no MER Package export | Connectors | `mer-review-agent-spec.md` §4 |
| 5 | **No per-client authorization** | Users can potentially access any client's QBO data | Auth | `controls.md` |
| 6 | **QBO token in-memory fallback** | Token loss in multi-instance deployments | Connectors | `mer-review-agent-spec.md` §8 |
| 7 | **AI Search public endpoint** | Search indexes accessible without VNet restriction | Infra | `controls.md` |
| 8 | **No automated E2E browser tests** | Manual smoke test is the only end-to-end validation | Testing | `docs/rules/STATUS.md` §7 |
| 9 | **Two MCP services dormant** | `DataToolService` and `GeneralService` not registered | MCP | `src/mcp_server/mcp_server.py` |
| 10 | **No rate limiting on review API** | QBO rate limit exhaustion possible | Backend | 🔍 Inferred |

### Documentation Gaps

| # | Gap | Priority |
|---|---|---|
| 1 | Google Drive credential management not documented | High |
| 2 | Data retention policy undefined | High |
| 3 | Incident response / escalation process missing | Medium |
| 4 | Per-rule config override documentation incomplete | Medium |
| 5 | Multi-currency handling behavior undocumented | Medium |
| 6 | Error codes and error handling contracts not documented | Medium |
| 7 | API rate limit and throttling behavior unclear | Low |

---

## Tech Debt

| # | Item | Effort | Impact |
|---|---|---|---|
| 1 | Remove QBO in-memory token fallback (require Cosmos) | Small | High — prevents token loss |
| 2 | Add per-client RBAC to review endpoints | Medium | High — security |
| 3 | Standardize error response format across all APIs | Medium | Medium — developer experience |
| 4 | Add structured logging with PII redaction | Medium | Medium — compliance |
| 5 | Convert manual smoke test to automated E2E suite | Large | High — regression confidence |
| 6 | Register or remove dormant MCP services | Small | Low — code hygiene |
| 7 | Add retry/backoff for QBO API calls | Medium | Medium — reliability |
| 8 | Document and test all MCP tool response contracts | Medium | Medium — API stability |

---

## Roadmap (by MVP Phase)

### MVP1 — Current (Balance Sheet + QBO)

✅ Largely complete. Remaining items:

| Item | Status | Priority |
|---|---|---|
| Remove in-memory QBO token fallback | ⚠️ Identified | High |
| Add per-client authorization | ⚠️ Not started | High |
| Automated E2E smoke test | ⚠️ Not started | Medium |
| PII redaction in logs | ⚠️ Not started | Medium |

### MVP2 — Google Drive + MER Package

| Item | Status | Priority |
|---|---|---|
| Google Drive evidence ingestion (real data) | 🔍 Connector exists, needs integration | High |
| Bank statement/petty cash parsing adapters | ⚠️ Partial (mock only) | High |
| MER Review Package export to Google Sheets | ⚠️ Not started | High |
| Drive folder permission model documentation | ⚠️ Not started | Medium |
| Evidence file versioning and change detection | ⚠️ Not started | Low |

### MVP3 — Profit & Loss Rules

| Item | Status | Priority |
|---|---|---|
| P&L rule definitions and implementations | ⚠️ Not started | High |
| P&L adapter enhancements | ⚠️ Not started | High |
| P&L UI integration | ⚠️ Not started | Medium |

### Future / Backlog

| Item | Category |
|---|---|
| Additional connector integrations (Dext, Plooto, Karbon) | Connectors |
| Multi-currency support | Rules |
| Client onboarding self-service | UX |
| Bulk review runs (multiple clients) | UX |
| AI-assisted anomaly detection (beyond deterministic rules) | Rules |
| Audit trail / change log for review runs | Compliance |
| SOC 2 readiness assessment | Compliance |
| Performance/load testing suite | Testing |
| VNet integration for AI Search | Security |

### V2 Agent Evolution (Approved — see [v2-implementation-spec.md](v2-implementation-spec.md))

| Phase | Item | Status | Timeline |
|---|---|---|---|
| 0 | Change `tool_choice` to `"auto"`, expand system prompt | ⚠️ Ready | 1 day |
| 1 | AccountingAgent + Evidence Ledger | ⚠️ Spec complete | 2-3 weeks |
| 2 | Correction Memory (per-client learning) | ⚠️ Spec complete | 2 weeks |
| 3 | Data Query Mode + PrepAgent (MER narratives) | ⚠️ Spec complete | 3-4 weeks |
| 4 | RAG Knowledge Base (policies, prior MERs) | ⚠️ Spec complete | 2-3 weeks |

Architecture decisions: [architecture-decision-record.md](architecture-decision-record.md) (10 ADRs)

---

## Priority Next Steps (Recommended)

### Immediate (This Sprint)

1. **Remove QBO in-memory token fallback** — prevents silent token loss in production
2. **Add per-client authorization guard** — block cross-client data access
3. **Document Drive credential management** — clarify setup for MVP2

### Near-Term (Next 2 Sprints)

4. **Build real bank statement adapters** — unblock evidence-dependent rules
5. **Add automated E2E smoke test** — automate the manual MVP1 checklist
6. **Implement structured PII-aware logging** — compliance and debugging

### Medium-Term (Next Quarter)

7. **Complete Google Drive integration** (MVP2)
8. **Build MER Review Package Sheet export** (MVP2)
9. **Design P&L rule framework** (MVP3 prep)
10. **VNet integration for AI Search** — address public endpoint gap

---

## Documentation TODOs

| Document | What's Needed |
|---|---|
| [integrations/qbo.md](integrations/qbo.md) | Verify retry/backoff behavior, token refresh exact flow |
| [integrations/google-drive-sheets.md](integrations/google-drive-sheets.md) | Document credential setup, folder structure conventions |
| [security-privacy.md](security-privacy.md) | Add data retention policy, incident response process |
| [rules-engine.md](rules-engine.md) | Add per-rule config override examples for each rule |
| (new) `docs/mer/api-reference.md` | Formal API contract documentation |
| (new) `docs/mer/error-handling.md` | Error codes, retry strategies, user-facing errors |
| (new) `docs/mer/runbook.md` | Full operational runbook with troubleshooting trees |
