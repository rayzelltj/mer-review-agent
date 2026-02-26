# Enkel MER Review Agent Specification (MVP Roadmap + Guardrails)

## 1. Purpose

This document defines the product and engineering source of truth for the **Enkel MER Review Agent** built on top of the MACAE platform.

Primary goal:
- Keep implementation aligned to the intended MER workflow so Copilot/Codex changes do not drift.

## 2. Product Intent

The MER Review Agent is a **Reviewer Copilot**, not a reviewer replacement.

It must:
- reduce review cycle time from hours to minutes,
- keep deterministic, explainable rule outcomes,
- preserve human professional judgment,
- leave an auditable output package.

## 3. Core User Outcomes (Non-Negotiable)

The user should be able to:

1. Open the web app and sign in with Microsoft work email.
2. Connect QuickBooks Online (QBO) for the selected client.
3. Select the company/client they want to review.
4. Run MER review for a specific month-end.
5. See a clean results view:
   - balance sheet for the review month,
   - balances for 3 prior months,
   - status per account/rule (`FAIL`, `PASS`, `NEEDS_REVIEW`, `WARN`, `NOT_APPLICABLE`),
   - concise rule details and next actions.
6. Ask follow-up questions in the same thread/session (chat-like continuity).
7. Run partial workflows (single statement, single rule family, single account scope), not only full-review runs.

## 4. MVP Scope by Phase

## MVP1 (Now)

In scope:
- QBO connector only.
- Balance sheet review points only.
- Deterministic rule engine execution.
- Web UI result presentation with current + prior 3 months.
- Chat continuity within same plan/thread.

Out of scope:
- Google Drive evidence ingestion.
- Google Sheet package generation.
- P&L rules.
- Dext/Plooto/Karbon connectors.

## MVP2

In scope:
- Google Drive connector for supporting documents.
- MER Review Package export to Google Sheets (storage + shareable output).
- Rule evidence linking from Drive docs.

## MVP3

In scope:
- Profit & Loss review rules and UX integration with existing run/review surfaces.

## 5. Recommended Agent Architecture

Chosen architecture for this repo:

1. **Orchestrator Agent**
- Owns session flow, scope selection, retries, and missing-data branching.

2. **Connector Agent (Tool-driven)**
- Pulls raw artifacts from QBO (and later Drive).
- Handles pagination/retry/backoff and normalized connector error codes.

3. **Normalization Agent**
- Converts raw connector payloads into stable snapshots/evidence bundles.
- No business judgment; purely schema/adapter behavior.

4. **Rules Engine Agent**
- Runs deterministic checks and emits structured rule results only.
- No free-form conclusions that conflict with rule outcomes.

5. **Review/Report Agent**
- Produces concise reviewer summary and formatted result payloads.
- Can answer follow-up questions using run artifacts + evidence references.

6. **HITL Agent (Optional)**
- Requests clarification/evidence when required inputs are missing.

Why this design:
- Separates retrieval from deterministic validation from narrative generation.
- Keeps explainability/auditability strong.
- Minimizes hallucination risk by grounding summary on structured findings.

## 6. Contract Boundaries (Implementation Guardrails)

Frontend:
- Keep UI orchestration in service/hooks layers, not ad-hoc in components.
- Preserve existing websocket + plan lifecycle.

Backend:
- Deterministic rule logic stays in rules engine.
- Connector/token logic stays in connector modules and API routers.
- Do not move privileged checks client-side.

MCP:
- Finance tools remain backend-facing with forwarded user auth context.
- Tool outputs should reference concrete run IDs and artifacts.

## 7. MER Data Contract (UI-Facing)

For balance sheet review results, `balance_sheet_view` should include:
- `period_columns`: current period + up to 3 prior period descriptors.
- `accounts[]` rows with:
  - `account`,
  - `status`,
  - `balances_by_period`,
  - `rule_hits`.
- `unmapped_findings` for non-account-scoped outcomes.

Status palette:
- `FAIL`, `NEEDS_REVIEW`, `WARN`, `PASS`, `NOT_APPLICABLE`.

## 8. Current Audit Findings (Repo-State)

Key issues observed and addressed in this cycle:

1. QBO OAuth reliability risk:
- Cosmos OAuth state persistence was allowed to silently fall back to in-memory state.
- In multi-instance deployments this can cause intermittent callback/state failures.

2. Result UX gap vs product intent:
- Balance sheet panel showed single-period balance instead of current + prior 3 months.

3. Context drift risk:
- No dedicated MER-specific implementation guardrail doc existed for assistant tooling.

## 9. Delivery Loop (How to Build Safely)

Use this loop for each change slice:

1. Diagnose current behavior from code + tests.
2. Plan smallest end-to-end slice.
3. Implement.
4. Add/adjust tests.
5. Verify in local test run.
6. Document contract changes.
7. Proceed to next slice.

Do not merge slices without passing step 4 and 5.

## 10. Verification Matrix

Minimum checks for MVP1 changes:

- Backend unit tests:
  - OAuth state persistence/read behavior.
  - Balance sheet view shaping.
  - Rule pipeline regression tests.

- Frontend tests:
  - Existing unit tests remain passing.
  - Rendering path handles multiple period columns.

- Manual smoke:
  - Login -> QBO connect -> callback -> status connected.
  - Run balance sheet review -> view shows 4 periods and rule statuses.
  - Follow-up prompt in same thread can reference run context.
  - Canonical runbook: `docs/architecture/mer-mvp1-smoke-checklist.md`
  - API helper: `scripts/smoke/mer_mvp1_api_smoke.sh`

## 11. Definition of Done (MVP1)

MVP1 is done when:

1. QBO connect flow is reliable and repeatable.
2. User can run balance sheet review for selected client + month-end.
3. Results clearly show current + prior 3 months with per-row status.
4. Deterministic rule outputs are traceable and explainable.
5. Tests pass for changed components.
6. This spec remains accurate to the implemented behavior.
