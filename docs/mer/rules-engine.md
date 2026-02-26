# Rules Engine — MER Review Agent

> **Status:** Living document
> **Confidence:** ✅ Verified in code
> **See also:** [docs/rules/STATUS.md](../rules/STATUS.md) (implementation checklist), [docs/rules/balance_sheet/](../rules/balance_sheet/) (per-rule specs)

---

## Overview

The rules engine is a **deterministic, stateless evaluation framework** that checks balance sheet accounts against defined review criteria. It has zero IO — all data arrives via a `RuleContext` dataclass, and all results are returned as structured `RuleResult` objects.

✅ *Verified in code:* `src/backend/common/rules_engine/`

---

## Rule Model / Contract

### Input: `RuleContext`

```python
@dataclass(frozen=True)
class RuleContext:
    period_end: date
    balance_sheet: BalanceSheetSnapshot
    prior_balance_sheets: tuple[BalanceSheetSnapshot, ...] = ()
    profit_and_loss: Optional[ProfitAndLossSnapshot] = None
    evidence: EvidenceBundle = EvidenceBundle()
    reconciliations: tuple[ReconciliationSnapshot, ...] = ()
    client_config: ClientRulesConfig = ClientRulesConfig()
```

✅ *Verified in code:* `src/backend/common/rules_engine/models.py`

### Output: `RuleResult`

```python
@dataclass
class RuleResult:
    rule_id: str
    rule_title: str
    status: RuleStatus
    severity: Severity          # Derived deterministically from status
    summary: str                # Human-readable explanation
    human_action: str           # What the reviewer should do
    details: list[dict]         # Per-account/item breakdown
    evidence_used: list[dict]   # References to evidence items
    best_practices_reference: str
    sources: list[str]          # ["QBO", "Drive", etc.]
```

### Aggregate Output: `RuleRunReport`

```python
@dataclass
class RuleRunReport:
    results: list[RuleResult]
    total_pass: int
    total_fail: int
    total_warn: int
    total_needs_review: int
    total_not_applicable: int
```

---

## Status & Severity

### Status Palette

| Status | Meaning | When Used |
|---|---|---|
| `PASS` | Check passed — no issues found | Evidence confirms expected state |
| `FAIL` | Check failed — action required | Material discrepancy or violation |
| `WARN` | Warning — review recommended | Minor discrepancy within tolerance |
| `NEEDS_REVIEW` | Insufficient data to determine | Missing evidence, stale dates, ambiguous |
| `NOT_APPLICABLE` | Rule doesn't apply | Disabled by config, no relevant accounts |

### Severity Mapping (Fixed Policy)

Severity is a **firm-policy derivative** of status — rules do not set severity independently:

| Status | Severity |
|---|---|
| `FAIL` | `HIGH` |
| `NEEDS_REVIEW` | `HIGH` |
| `WARN` | `MEDIUM` |
| `PASS` | `LOW` |
| `NOT_APPLICABLE` | `NONE` |

✅ *Verified in code:* `src/backend/common/rules_engine/models.py` — `STATUS_TO_SEVERITY` mapping

### Status Aggregation

When a rule evaluates multiple accounts, the overall status is determined by `StatusOrdering.worst()`:

```
FAIL(50) > NEEDS_REVIEW(40) > WARN(30) > PASS(20) > NOT_APPLICABLE(10)
```

The highest-priority (worst) status wins.

✅ *Verified in code:* `src/backend/common/rules_engine/models.py` — `StatusOrdering`

---

## Rule Registration

Rules are registered via the `@register_rule` decorator at import time:

```python
from ..registry import register_rule
from ..rule import Rule

@register_rule
class BSUndepositedFundsZero(Rule):
    rule_id = "BS-UNDEPOSITED-FUNDS-ZERO"
    rule_title = "Undeposited Funds Zero"
    best_practices_reference = "Zero-Balance Checks"
    sources = ["QBO"]
    config_model = UndepositedFundsConfig

    def evaluate(self, ctx: RuleContext) -> RuleResult:
        ...
```

The `RuleRegistry` is a singleton dict keyed by `rule_id`. Importing `src/backend/common/rules_engine/rules/__init__.py` triggers auto-registration of all rules.

✅ *Verified in code:* `src/backend/common/rules_engine/registry.py`, `src/backend/common/rules_engine/rules/__init__.py`

---

## Implemented Rules (26 Total)

### Bank & Reconciliation

| Rule ID | Title | What It Checks |
|---|---|---|
| `BS-BANK-CC-RECONCILED-THROUGH-PERIOD-END` | Bank/CC Reconciled | Register balance − statement balance = expected outstanding vs unreconciled sums |
| `BS-UNCLEARED-ITEMS-INVESTIGATED-AND-FLAGGED` | Uncleared Items | Flags uncleared items older than 2 months |
| `BS-UNDEPOSITED-FUNDS-ZERO` | Undeposited Funds Zero | Account balance must be zero (configurable threshold) |

### Clearing & Zero-Balance

| Rule ID | Title | What It Checks |
|---|---|---|
| `BS-CLEARING-ACCOUNTS-ZERO` | Sales Clearing Zero | Current Asset clearing accounts within platform threshold |
| `BS-CLEARING-ACCOUNTS-NON-SALES-ZERO` | Non-Sales Clearing Zero | Non-sales clearing must be exactly zero |
| `BS-PLOOTO-CLEARING-ZERO` | Plooto Clearing Zero | Plooto Clearing must be exactly zero |
| `BS-PLOOTO-INSTANT-BALANCE-DISCLOSURE` | Plooto Instant Disclosure | Disclosure-only check (no evidence required) |

### AP/AR Subledger

| Rule ID | Title | What It Checks |
|---|---|---|
| `BS-AP-SUBLEDGER-RECONCILES` | AP Subledger Reconciles | AP aging summary + detail totals match Balance Sheet |
| `BS-AR-SUBLEDGER-RECONCILES` | AR Subledger Reconciles | AR aging summary + detail totals match Balance Sheet |
| `BS-AP-AR-ITEMS-OLDER-THAN-60-DAYS` | AP/AR Items >60 Days | Flags aged items and summary/detail discrepancies |
| `BS-AP-AR-NEGATIVE-OPEN-ITEMS` | AP/AR Negative Items | Flags negative open balances in aging detail |
| `BS-AP-AR-PAID-AFTER-MONTH-END-NOTED` | Paid After Month-End | Flags items paid after period-end |
| `BS-AP-AR-YEAR-END-BATCH-ADJUSTMENTS` | Year-End Batch Adjustments | Flags generic year-end adjustment names in aging detail |

### Intercompany

| Rule ID | Title | What It Checks |
|---|---|---|
| `BS-AP-AR-INTERCOMPANY-OR-SHAREHOLDER-PAID` | Intercompany/Shareholder | Flags intercompany balances missing/mismatched in counterpart BS |
| `BS-INTERCOMPANY-BALANCES-RECONCILE` | Intercompany Reconcile | Loan balances reconcile across related companies |

### Evidence Match

| Rule ID | Title | What It Checks |
|---|---|---|
| `BS-LOAN-BALANCE-MATCH` | Loan Balance Match | BS loan balance matches loan schedule evidence |
| `BS-INVESTMENT-BALANCE-MATCH` | Investment Balance Match | BS investment balance matches statement evidence |
| `BS-PETTY-CASH-MATCH` | Petty Cash Match | BS petty cash matches support evidence |
| `BS-WORKING-PAPER-RECONCILES` | Working Paper Reconciles | Working paper balance matches BS |

### Fixed Assets

| Rule ID | Title | What It Checks |
|---|---|---|
| `BS-FIXED-ASSET-REGISTER-RECONCILES` | Fixed Asset Register | Fixed asset register matches BS |
| `BS-FIXED-ASSET-CAPITALIZATION-THRESHOLD` | Capitalization Threshold | Checks capitalization threshold compliance |

### Tax

| Rule ID | Title | What It Checks |
|---|---|---|
| `BS-TAX-FILINGS-UP-TO-DATE` | Tax Filings Current | Sales tax filings completed through most recent period |
| `BS-TAX-PAYABLE-AND-SUSPENSE-RECONCILE-TO-RETURN` | Tax Payable Reconcile | Tax payable/suspense reconciles to most recent return |

### Trend / Prior Period

| Rule ID | Title | What It Checks |
|---|---|---|
| `BS-BALANCE-UNCHANGED-PRIOR-MONTH` | Balance Unchanged | Flags accounts with zero change from prior month |

✅ *Verified in code:* `src/backend/common/rules_engine/rules/` (26 files), `docs/rules/STATUS.md`

---

## Per-Rule Configuration

Every rule has a typed Pydantic config model. Common base fields:

| Field | Default | Purpose |
|---|---|---|
| `enabled` | `True` | Enable/disable the rule |
| `missing_data_policy` | `NEEDS_REVIEW` | What to return when evidence is missing |
| `tolerance` | `None` | Amount tolerance for comparisons (exact if None) |

Client-specific overrides are provided via `ClientRulesConfig` in the `RuleContext`:

```python
class ClientRulesConfig(BaseModel):
    rules: Dict[str, Dict[str, Any]] = {}

    def get_rule_config(self, rule_id: str, model: Type[T], default=None) -> T:
        ...
```

✅ *Verified in code:* `src/backend/common/rules_engine/config.py`

---

## Evidence Requirements

Each rule declares what evidence it needs via `EVIDENCE_REQUIREMENTS` in `src/backend/common/rules_engine/evidence_requirements.py`. Each spec includes:

- **config_field** — the config field name for the evidence type
- **source** — `"Drive"` or `"QBO"`
- **description** — human-readable explanation
- **adapter_path** — dotted path to the adapter function

The API uses these declarations to tell the frontend what evidence is missing and how to obtain it.

### Evidence Types (20 Implemented)

| Evidence Type | Required Fields | Used By |
|---|---|---|
| `statement_balance_attachment` | `amount`, `statement_end_date`, `meta.account_ref` | Bank reconciled |
| `petty_cash_support` | `amount` | Petty cash match |
| `loan_schedule_balance` | `amount`, `as_of_date` | Loan balance match |
| `investment_statement_balance` | `amount`, `as_of_date` | Investment balance match |
| `ap_aging_summary_total` | `amount`, `as_of_date` | AP subledger reconciles |
| `ap_aging_detail_total` | `amount`, `as_of_date` | AP subledger reconciles |
| `ar_aging_summary_total` | `amount`, `as_of_date` | AR subledger reconciles |
| `ar_aging_detail_total` | `amount`, `as_of_date` | AR subledger reconciles |
| `ap_aging_summary_over_60` | `amount`, `as_of_date`, `meta.items[]` | AP/AR items >60 days |
| `ap_aging_detail_over_60` | `amount`, `as_of_date`, `meta.items[]` | AP/AR items >60 days |
| `ar_aging_summary_over_60` | `amount`, `as_of_date`, `meta.items[]` | AP/AR items >60 days |
| `ar_aging_detail_over_60` | `amount`, `as_of_date`, `meta.items[]` | AP/AR items >60 days |
| `ap_aging_detail_rows` | `amount`, `as_of_date`, `meta.items[]` | AP/AR negative open items |
| `ar_aging_detail_rows` | `amount`, `as_of_date`, `meta.items[]` | AP/AR negative open items |
| `intercompany_balance_sheet` | `as_of_date`, `meta.items[]` | Intercompany/shareholder |
| `working_paper_balance` | `amount`, `as_of_date` | Working paper reconciles |
| `tax_agencies` | `meta.items[]` | Tax filings, tax payable |
| `tax_returns` | `meta.items[]` | Tax filings, tax payable |
| `tax_payments` | `meta.items[]` | Tax payable/suspense |

✅ *Verified in code:* `docs/rules/STATUS.md` §5, `src/backend/common/rules_engine/evidence_requirements.py`

---

## Drive-Only Rules

Some rules require Google Drive evidence and are auto-disabled when no Drive manifest is configured:

```python
DRIVE_ONLY_RULE_IDS = {
    "BS-INVESTMENT-BALANCE-MATCH",
    "BS-LOAN-BALANCE-MATCH",
    "BS-PETTY-CASH-MATCH",
    "BS-WORKING-PAPER-RECONCILES",
}
```

✅ *Verified in code:* `src/backend/api/reviews.py`

---

## Edge Cases & Assumptions

| Assumption | Impact | Status |
|---|---|---|
| Account matching by `account_ref` or name inference | May miss accounts with unexpected naming | ✅ Implemented with fallback patterns |
| Tolerance is exact (0) by default | Small rounding differences trigger FAIL | ✅ Configurable per-rule |
| `missing_data_policy` defaults to `NEEDS_REVIEW` | Missing evidence doesn't auto-PASS or auto-FAIL | ✅ Configurable |
| Prior period balance sheets may not always be available | Rules using prior periods gracefully degrade | ✅ Handled in rules |
| QBO date formats may vary by locale | Adapter date parsing handles multiple formats | ✅ `src/mcp_server/utils/date_utils.py` |

---

## How to Add a New Rule

### 1. Create the rule file

Create `src/backend/common/rules_engine/rules/bs_your_new_rule.py`:

```python
from ..registry import register_rule
from ..rule import Rule
from ..models import RuleContext, RuleResult, RuleStatus
from ..config import YourNewRuleConfig  # define in config.py

@register_rule
class BSYourNewRule(Rule):
    rule_id = "BS-YOUR-NEW-RULE"
    rule_title = "Your New Rule Title"
    best_practices_reference = "Category Reference"
    sources = ["QBO"]  # or ["QBO", "Drive"]
    config_model = YourNewRuleConfig

    def evaluate(self, ctx: RuleContext) -> RuleResult:
        cfg = ctx.client_config.get_rule_config(self.rule_id, YourNewRuleConfig)
        if not cfg.enabled:
            return RuleResult(status=RuleStatus.NOT_APPLICABLE, ...)

        # Your deterministic logic here
        ...
```

### 2. Add the config model

In `src/backend/common/rules_engine/config.py`, add:

```python
class YourNewRuleConfig(BaseRuleConfig):
    # Add rule-specific config fields
    threshold: Decimal = Decimal("0")
```

### 3. Register the import

Add the import to `src/backend/common/rules_engine/rules/__init__.py`:

```python
from .bs_your_new_rule import BSYourNewRule
```

### 4. Add evidence requirements (if applicable)

Update `src/backend/common/rules_engine/evidence_requirements.py` to declare what evidence the rule needs.

### 5. Write tests

Create `src/backend/tests/rules_engine/test_bs_your_new_rule.py` with cases for:
- `PASS` — expected conditions met
- `FAIL` — material discrepancy
- `WARN` — within tolerance but flagged
- `NEEDS_REVIEW` — missing evidence, stale dates
- `NOT_APPLICABLE` — disabled or no relevant accounts

### 6. Document the rule

Create `docs/rules/balance_sheet/BS-YOUR-NEW-RULE.md` following the existing format.

### 7. Update the status checklist

Add the rule to `docs/rules/STATUS.md`.

---

## Execution

The rules engine is invoked by the review API:

```
POST /api/reviews/rules
  → src/backend/api/reviews.py
    → RulesRunner(registry).run(context, rule_ids=optional_filter)
      → for each rule in registry:
          rule.evaluate(context) → RuleResult
      → aggregate into RuleRunReport
```

Individual rules can be run via the optional `rule_ids` filter parameter.

✅ *Verified in code:* `src/backend/common/rules_engine/runner.py`, `src/backend/api/reviews.py`
