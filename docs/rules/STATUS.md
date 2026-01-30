# Rules Engine Status Checklist

This checklist tracks **what exists**, **what’s working**, and **what’s missing** across the balance sheet rules,
evidence pipeline, and end-to-end flow. It is meant to be updated as you add real connectors, adapters, and UI output.

---

## 1) End-to-end flow (high level)

- [x] Rules engine core models (`RuleContext`, `RuleResult`, `EvidenceBundle`)
- [x] Rule registry + runner
- [x] Balance Sheet rules implemented (see section 3)
- [x] QBO report adapters (Balance Sheet, Profit & Loss, Accounts)
- [x] Mock evidence adapters (JSON fixtures → EvidenceBundle/ReconciliationSnapshot)
- [ ] **Connectors** (QBO OAuth + API fetch, Google Drive fetch, uploads, email, etc.)
- [ ] **File extraction** layer (PDF/text extraction, OCR, CSV/Sheets parsing)
- [ ] **Evidence normalization** for real bank statements, petty cash docs, Plooto screenshots
- [ ] **UI output** for rule results and evidence traceability

---

## 2) Connectors (data acquisition)

**QBO**
- [ ] OAuth/token storage
- [ ] Report fetchers (Balance Sheet, P&L)
- [ ] Account list fetcher
- [ ] Pagination + retry handling

**Google Drive / file storage**
- [ ] File listing + download
- [ ] Versioning + file metadata capture
- [ ] Access control / permission auditing

**Uploads / email**
- [ ] Manual upload intake
- [ ] Email attachment intake

---

## 3) Balance Sheet rules (implemented)

All listed rules are implemented in `src/backend/common/rules_engine/rules/` and documented under `docs/rules/balance_sheet/`.

- [x] **BS-BANK-RECONCILED-THROUGH-PERIOD-END**
  - Requires reconciliation snapshots + **statement attachment** evidence
  - Requires register balance vs Balance Sheet tie-out
  - Requires maintenance count check vs inferred bank/cc accounts
  - Tests: PASS / FAIL / NEEDS_REVIEW cases
- [x] **BS-UNCLEARED-ITEMS-INVESTIGATED-AND-FLAGGED**
  - Flags uncleared items > 2 months old
  - Tests: PASS / WARN / NEEDS_REVIEW
- [x] **BS-UNDEPOSITED-FUNDS-ZERO**
  - Zero-balance rule with configured thresholds
  - Tests: PASS / WARN / FAIL / NEEDS_REVIEW
- [x] **BS-CLEARING-ACCOUNTS-ZERO**
  - Zero-balance rule with name inference (`clearing`)
  - Tests: PASS / WARN / FAIL / NEEDS_REVIEW
- [x] **BS-PETTY-CASH-MATCH**
  - Compares petty cash support evidence vs Balance Sheet
  - Tests: PASS / FAIL / NEEDS_REVIEW
- [x] **BS-PLOOTO-INSTANT-BALANCE-DISCLOSURE**
  - Requires Plooto live balance evidence as-of period end
  - Tests: PASS / FAIL / NEEDS_REVIEW

---

## 4) Adapters (normalization)

**QBO adapters (implemented)**
- [x] Balance Sheet report → `BalanceSheetSnapshot`
- [x] P&L report → `ProfitAndLossSnapshot`
- [x] Accounts payload → account type/subtype map
- [x] Pipeline helper for assembling snapshots

**Mock evidence adapters (implemented)**
- [x] JSON evidence manifest → `EvidenceBundle`
- [x] JSON reconciliation report → `ReconciliationSnapshot`

**Evidence adapters (real data) — missing**
- [ ] Bank statement/activity statement parsing (PDF/CSV/Sheets)
- [ ] Petty cash support parsing (PDF/Image/Sheet)
- [ ] Plooto Instant evidence parsing (screenshot/PDF export)

---

## 5) Evidence types & required fields

**Implemented evidence types (rules expect these)**

- [x] `statement_balance_attachment`
  - Required fields: `amount`, `statement_end_date`, `meta.account_ref`
  - Used by: Bank reconciled rule
- [x] `petty_cash_support`
  - Required fields: `amount`
  - Used by: Petty cash match rule
- [x] `plooto_instant_live_balance`
  - Required fields: `amount`, `as_of_date`
  - Used by: Plooto Instant balance rule

**Missing**
- [ ] Structured evidence for other balance sheet rules (if added later)

---

## 6) Fixtures & sample data

**QBO fixtures**
- [x] Balance Sheet report sample
- [x] Accounts query sample
- [x] Profit & Loss report sample

**Bank reconciliation fixtures**
- [x] Blackbird Fabrics reconciliation reports (AUD/CAD)
- [x] PayPal activity statement sample
- [x] Maintenance list sample

**Evidence fixtures**
- [x] Evidence manifest (mock)
- [x] Petty cash support placeholder (mock)
- [ ] Real petty cash support sample (PDF/scan/Sheet)
- [ ] Real Plooto Instant evidence sample (screenshot/export)

---

## 7) Tests

**Rules engine**
- [x] Unit tests for all balance sheet rules
- [x] Blackbird Fabrics reconciliation sample tests

**Adapters**
- [x] QBO adapter unit tests
- [x] Mock evidence adapter unit tests

**Missing**
- [ ] Integration tests with real connectors
- [ ] End-to-end tests with UI output

---

## 8) UI output

- [ ] UI rendering of `RuleRunReport` summaries
- [ ] Evidence traceability UI (show evidence item(s) used per rule)
- [ ] Drill-down view per account/rule

---

## 9) Open data gaps (to unblock real adapters)

- [ ] Actual reconciliation export format(s) from QBO and/or client systems
- [ ] Bank statement formats (PDF/CSV/Sheets) per bank/provider
- [ ] Petty cash support examples
- [ ] Plooto Instant balance evidence example(s)

---

## 10) Next actions (recommended order)

1. **Collect real evidence samples** (petty cash, bank statements, Plooto live balance)
2. **Build extraction adapters** (PDF/CSV/Sheets → normalized evidence)
3. **Implement connectors** (QBO + Google Drive)
4. **Wire end-to-end run** (connectors → adapters → rules → UI)
