# Testing & Validation — MER Review Agent

> **Status:** Living document
> **Confidence:** ✅ Verified in code
> **See also:** [docs/rules/STATUS.md](../rules/STATUS.md) §7, [docs/architecture/mer-mvp1-smoke-checklist.md](../architecture/mer-mvp1-smoke-checklist.md)

---

## Test Strategy

The project uses **pytest** with `pytest-asyncio` for backend tests. The testing approach emphasizes:

1. **1:1 rule coverage** — each of the 26 balance sheet rules has a dedicated test file
2. **Adapter coverage** — each QBO/evidence adapter has its own test file
3. **Fixture-driven integration** — real client data fixtures verify deterministic pipeline output
4. **Contract tests** — HTTP route and API contract verification
5. **Manual smoke tests** — documented runbook for end-to-end QBO → review → results

✅ *Verified in code:* `pytest.ini`, `conftest.py`, `src/backend/tests/`

---

## Test Configuration

### `pytest.ini`
```ini
[pytest]
addopts = -p pytest_asyncio
```

### `conftest.py`

Provides shared fixtures:

| Fixture | Purpose |
|---|---|
| `period_end` | Fixed `date(2025, 1, 31)` for deterministic tests |
| `make_bs_line` | Factory for `BalanceSheetLine` |
| `make_bs_snapshot` | Factory for `BalanceSheetSnapshot` |
| `make_evidence` | Factory for `EvidenceItem` with single item |
| `make_bundle` | Factory for `EvidenceBundle` |
| `make_context` | Factory for complete `RuleContext` |

✅ *Verified in code:* `conftest.py` (workspace root)

---

## Test Inventory

### Rules Engine Tests (26 files)

Location: `src/backend/tests/rules_engine/`

| Test File | Rule Tested | Status Cases Covered |
|---|---|---|
| `test_bs_ap_subledger_reconciles.py` | BS-AP-SUBLEDGER-RECONCILES | PASS, FAIL (summary/detail mismatch), NEEDS_REVIEW, NOT_APPLICABLE |
| `test_bs_ar_subledger_reconciles.py` | BS-AR-SUBLEDGER-RECONCILES | PASS, FAIL, NEEDS_REVIEW, NOT_APPLICABLE |
| `test_bs_ap_ar_items_older_than_60_days.py` | BS-AP-AR-ITEMS-OLDER-THAN-60-DAYS | PASS, NEEDS_REVIEW |
| `test_bs_ap_ar_negative_open_items.py` | BS-AP-AR-NEGATIVE-OPEN-ITEMS | PASS, NEEDS_REVIEW |
| `test_bs_ap_ar_intercompany.py` | BS-AP-AR-INTERCOMPANY-OR-SHAREHOLDER-PAID | PASS, NEEDS_REVIEW |
| `test_bs_ap_ar_year_end_batch_adjustments.py` | BS-AP-AR-YEAR-END-BATCH-ADJUSTMENTS | PASS, NEEDS_REVIEW, NOT_APPLICABLE |
| `test_bs_ap_ar_paid_after_month_end.py` | BS-AP-AR-PAID-AFTER-MONTH-END-NOTED | PASS, NEEDS_REVIEW |
| `test_bs_bank_cc_reconciled.py` | BS-BANK-CC-RECONCILED-THROUGH-PERIOD-END | PASS, WARN, NEEDS_REVIEW |
| `test_bs_uncleared_items.py` | BS-UNCLEARED-ITEMS-INVESTIGATED-AND-FLAGGED | PASS, WARN, NEEDS_REVIEW |
| `test_bs_undeposited_funds_zero.py` | BS-UNDEPOSITED-FUNDS-ZERO | PASS, WARN, FAIL, NEEDS_REVIEW |
| `test_bs_clearing_accounts_zero.py` | BS-CLEARING-ACCOUNTS-ZERO | PASS, WARN, FAIL, NEEDS_REVIEW, NOT_APPLICABLE |
| `test_bs_clearing_accounts_non_sales_zero.py` | BS-CLEARING-ACCOUNTS-NON-SALES-ZERO | PASS, FAIL, NEEDS_REVIEW, NOT_APPLICABLE |
| `test_bs_plooto_clearing_zero.py` | BS-PLOOTO-CLEARING-ZERO | PASS, FAIL, NEEDS_REVIEW, NOT_APPLICABLE |
| `test_bs_plooto_instant_balance_disclosure.py` | BS-PLOOTO-INSTANT-BALANCE-DISCLOSURE | PASS, WARN, NEEDS_REVIEW, NOT_APPLICABLE |
| `test_bs_petty_cash_match.py` | BS-PETTY-CASH-MATCH | PASS, FAIL, NEEDS_REVIEW |
| `test_bs_loan_balance_match.py` | BS-LOAN-BALANCE-MATCH | PASS, FAIL, NEEDS_REVIEW, NOT_APPLICABLE |
| `test_bs_investment_balance_match.py` | BS-INVESTMENT-BALANCE-MATCH | PASS, FAIL, NEEDS_REVIEW, NOT_APPLICABLE |
| `test_bs_intercompany_balances_reconcile.py` | BS-INTERCOMPANY-BALANCES-RECONCILE | PASS, NEEDS_REVIEW, NOT_APPLICABLE |
| `test_bs_working_paper_reconciles.py` | BS-WORKING-PAPER-RECONCILES | PASS, FAIL, NEEDS_REVIEW, NOT_APPLICABLE |
| `test_bs_balance_unchanged_prior_month.py` | BS-BALANCE-UNCHANGED-PRIOR-MONTH | (various) |
| `test_bs_fixed_asset_register.py` | BS-FIXED-ASSET-REGISTER-RECONCILES | (various) |
| `test_bs_fixed_asset_capitalization.py` | BS-FIXED-ASSET-CAPITALIZATION-THRESHOLD | (various) |
| `test_bs_tax_filings_up_to_date.py` | BS-TAX-FILINGS-UP-TO-DATE | PASS, FAIL, NEEDS_REVIEW, NOT_APPLICABLE |
| `test_bs_tax_payable_reconcile.py` | BS-TAX-PAYABLE-AND-SUSPENSE-RECONCILE-TO-RETURN | PASS, WARN, NEEDS_REVIEW, NOT_APPLICABLE |

Additional rules engine tests:
- `test_blackbird_fabrics_samples_bank_reconciled.py` — real client fixture verification
- `test_live_balance_review.py` — integration pipeline test

### Adapter Tests (12 files)

Location: `src/backend/tests/adapters/`

| Test File | What It Tests |
|---|---|
| `test_qbo_balance_sheet_adapter.py` | QBO BS JSON → `BalanceSheetSnapshot` |
| `test_qbo_balance_sheet_blackbird.py` | Blackbird Fabrics-specific BS parsing |
| `test_qbo_accounts_adapter.py` | QBO Accounts JSON → type/subtype map |
| `test_qbo_accounts_blackbird.py` | Blackbird-specific account parsing |
| `test_qbo_aging_reports.py` | QBO aging JSON → totals/items |
| `test_qbo_fixed_assets_adapter.py` | Fixed asset adapter |
| `test_qbo_profit_and_loss_adapter.py` | QBO P&L JSON → `ProfitAndLossSnapshot` |
| `test_qbo_tax_adapter.py` | QBO tax data → tax models |
| `test_bank_statement_parsers.py` | Bank statement CSV/PDF parsing |
| `test_working_paper_prepaid_schedule.py` | Prepaid schedule CSV parsing |
| `test_working_paper_fixed_asset_register.py` | Fixed asset register CSV parsing |
| `test_evidence_requirements.py` | Evidence requirement resolution |

### API / Integration Tests

| Test File | What It Tests |
|---|---|
| `tests/api/test_app_route_wiring.py` | All routes are mounted correctly |
| `tests/api/test_http_route_contracts.py` | HTTP contract validation |
| `tests/connectors/test_qbo_client.py` | QBO client behavior |
| `tests/connectors/test_qbo_oauth_state_store.py` | OAuth token persistence |
| `tests/connectors/test_qbo_reports.py` | QBO report fetching |
| `tests/connectors/test_drive_client.py` | Drive client |
| `tests/connectors/test_drive_config.py` | Drive configuration |
| `tests/pipelines/test_balance_sheet_view.py` | End-to-end BS view shaping |
| `tests/pipelines/test_live_qbo_drive.py` | Live QBO + Drive pipeline |

### Agent / MCP Tests

Location: `src/tests/`

| Test File | What It Tests |
|---|---|
| `agents/test_foundry_integration.py` | AI Foundry agent integration |
| `agents/test_human_approval_manager.py` | Plan approval flow |
| `agents/test_proxy_agent.py` | ProxyAgent behavior |
| `agents/test_reasoning_agent.py` | Reasoning agent |
| `mcp_server/test_factory.py` | MCP tool factory/registration |
| `mcp_server/test_fastmcp_run.py` | MCP server startup |
| `mcp_server/test_hr_service.py` | HR service tools |
| `mcp_server/test_utils.py` | MCP utility functions |

### Test Fixtures

Location: `src/backend/tests/fixtures/`

| Directory | Contents |
|---|---|
| `fixtures/blackbird/` | Full QBO JSON snapshots for Blackbird Fabrics (BS, P&L, accounts, aging, trial balance, transactions), CSV working papers, evidence manifests — multi-period |
| `fixtures/` | Sample QBO API JSON responses, evidence manifest fixtures |

✅ *Verified in code:* `src/backend/tests/fixtures/`

---

## Running Tests

```bash
# All backend tests (recommended: from src/backend/)
cd src/backend
uv run pytest --tb=short -q

# Rules engine only
uv run pytest tests/rules_engine/ -v

# Specific rule
uv run pytest tests/rules_engine/test_bs_undeposited_funds_zero.py -v

# Adapters only
uv run pytest tests/adapters/ -v

# API/connector tests
uv run pytest tests/api/ tests/connectors/ -v

# With coverage (if configured)
uv run pytest --cov=common/rules_engine tests/rules_engine/ -v
```

---

## Test Pattern (Rules)

Each rule test follows a consistent pattern:

```python
class TestBSExampleRule:
    def test_pass(self, make_context, make_bs_line, make_bundle, ...):
        # Arrange: build RuleContext with passing data
        ctx = make_context(
            balance_sheet=make_bs_snapshot([make_bs_line(...)]),
            evidence=make_bundle([make_evidence(...)]),
        )
        # Act: evaluate rule
        rule = BSExampleRule()
        result = rule.evaluate(ctx)
        # Assert
        assert result.status == RuleStatus.PASS
        assert result.severity == Severity.LOW

    def test_fail(self, make_context, ...):
        # Arrange: build RuleContext with failing data
        ...
        assert result.status == RuleStatus.FAIL
        assert result.severity == Severity.HIGH

    def test_needs_review_missing_evidence(self, make_context, ...):
        # Arrange: build RuleContext with missing evidence
        ...
        assert result.status == RuleStatus.NEEDS_REVIEW

    def test_not_applicable_disabled(self, make_context, ...):
        # Arrange: build RuleContext with rule disabled
        ...
        assert result.status == RuleStatus.NOT_APPLICABLE
```

---

## Coverage Gaps

### What Is Well Covered ✅

| Area | Coverage |
|---|---|
| Individual rule logic | 26/26 rules have dedicated tests |
| QBO adapter parsing | Full adapter test suite |
| Evidence model resolution | Evidence requirements tests |
| HTTP route wiring | Route contract tests |
| Connector behavior | QBO + Drive client tests |

### What Is Missing or Partial ⚠️

| Gap | Impact | Priority |
|---|---|---|
| **Integration tests with real QBO** | Can't verify adapter accuracy with live data | High |
| **End-to-end UI tests** | No automated browser-based testing | High |
| **WebSocket message flow tests** | WS streaming not tested end-to-end | Medium |
| **MCP tool response contract tests** | MCP tool outputs not formally validated | Medium |
| **Frontend component tests** | React component test coverage unclear | Medium |
| **Auth flow tests (EasyAuth/MSAL)** | Auth module tests exist but may not cover all paths | Medium |
| **Multi-client concurrent review** | No tests for parallel review runs | Low |
| **Error/retry handling** | QBO API failure scenarios not tested | Medium |
| **Performance/load tests** | No load testing for review pipeline | Low |

✅ *Verified in code:* `docs/rules/STATUS.md` §7

---

## Manual Smoke Test

For post-deployment or major change verification, use:

📋 **[MVP1 Smoke Checklist](../architecture/mer-mvp1-smoke-checklist.md)**

This covers:
1. Login + session validation
2. QBO connect + callback flow
3. Connected-state refresh
4. Company selection + review run
5. Result rendering with 4-period balances

---

## Suggested Additions

### Fixture-Based Rule Regression Tests

For every rule, add a "golden output" test using real client fixtures:

```python
def test_blackbird_fabrics_full_pipeline():
    """Deterministic regression: same fixtures → same results every time."""
    context = load_blackbird_fabrics_context("2025-01-31")
    runner = RulesRunner()
    report = runner.run(context)

    assert report.total_pass == <expected>
    assert report.total_fail == <expected>
    assert report.total_needs_review == <expected>
    # Per-rule assertions for critical rules
```

### Contract Tests for MCP Tools

```python
def test_finance_tool_response_schema():
    """Verify MCP finance tool responses match expected schema."""
    response = call_mcp_tool("check_qbo_connection", {...})
    assert "connected" in response
    assert isinstance(response["connected"], bool)
```

### Review Run State Machine Test

```python
def test_review_run_lifecycle():
    """Verify review run state transitions: queued → running → done/failed."""
    run = create_review_run(client_id="test", period_end="2025-01-31")
    assert run.status == "queued"
    # ... trigger processing ...
    assert run.status in ("done", "failed")
```
