# Rules Engine (Source-Agnostic)

This package implements **domain logic** for MER rules.

- Rules operate on **snapshots** (Balance Sheet, P&L), **evidence**, and **client configuration**.
- Rules **must not** call QBO, Google Drive, or any network/API directly.
- Adapters (QBO/Drive/etc.) should live elsewhere and only *produce* the inputs this engine needs.

## Core Concepts

### Inputs

- `BalanceSheetSnapshot` (`common.rules_engine.models.BalanceSheetSnapshot`)
  - `as_of_date`
  - `accounts[]` with `account_ref`, `name`, `balance` (plus optional type/subtype)
- `ProfitAndLossSnapshot` (`common.rules_engine.models.ProfitAndLossSnapshot`)
  - Holds `totals` (we currently expect `totals["revenue"]` when using revenue-based tolerances)
- `EvidenceBundle` (`common.rules_engine.models.EvidenceBundle`)
  - Holds `EvidenceItem` objects (e.g., petty cash support amount)
- `ClientRulesConfig` (`common.rules_engine.config.ClientRulesConfig`)
  - Holds per-rule config payloads keyed by `rule_id`

All of these can be created from:
- real QBO reports later (adapter layer), or
- JSON fixtures/sample data for deterministic unit tests.

### Outputs

Each rule returns a `RuleResult`:
- `status`: `PASS | WARN | FAIL | NEEDS_REVIEW | NOT_APPLICABLE`
- `severity`: `INFO | LOW | MEDIUM | HIGH | CRITICAL`
- `summary`: human-readable short summary
- `details[]`: structured findings (per account/evidence item)
- `evidence_used[]`: evidence items (when relevant)
- `human_action`: explicit reviewer instruction when not a clean PASS

## How Rules Run (Registration → Runner)

### Registration

Rules are classes that:
- inherit from `common.rules_engine.rule.Rule`
- are decorated with `@register_rule` (`common.rules_engine.registry.register_rule`)

The decorator registers the rule class in the global registry (`common.rules_engine.registry.registry`).

Important: registration only happens when the module is imported. The package ensures the built-in
rules are imported (and therefore registered) from `common.rules_engine.__init__`.

### Running

- Construct a `RuleContext` (period end + snapshots + evidence + client config)
- Call `RulesRunner().run(ctx)` to receive a `RuleRunReport` with:
  - `results[]` (one per executed rule)
  - `totals` (count by status)

Example:

```python
from datetime import date
from common.rules_engine import RulesRunner, RuleContext
from common.rules_engine.models import BalanceSheetSnapshot
from common.rules_engine.config import ClientRulesConfig

ctx = RuleContext(
    period_end=date(2025, 12, 31),
    balance_sheet=BalanceSheetSnapshot(as_of_date=date(2025, 12, 31), accounts=[]),
    client_config=ClientRulesConfig(rules={}),
)

report = RulesRunner().run(ctx)
```

## Adding a New Rule

1) Create a new file under `common/rules_engine/rules/`, e.g. `my_new_rule.py`
2) Implement a rule class:
   - set `rule_id`, `rule_title`, `best_practices_reference`, `sources`, `config_model`
   - implement `evaluate(self, ctx: RuleContext) -> RuleResult`
   - decorate the class with `@register_rule`
3) Ensure the module is imported so it registers:
   - add it to `common.rules_engine.rules.__init__` (recommended)
4) Add unit tests under `tests/rules_engine/` with fixtures that cover:
   - PASS case
   - WARN case (if applicable)
   - FAIL case (if applicable)
   - missing-data case (NEEDS_REVIEW/NOT_APPLICABLE)

## Testing

Rules engine tests are pure Python and do not require Azure/QBO.

From `src/backend`:

```bash
uv run pytest -q tests/rules_engine
```

`tests/conftest.py` ensures `src/backend` is on `sys.path` so imports like `import common...` work.

## Rule Catalog (Tracking All Rules)

The engine can generate a machine-readable catalog from the registered rule classes.

For a human-readable spec, see `common/rules_engine/specs/` (one file per rule).

From `src/backend`:

```bash
python -m common.rules_engine.catalog > rules_catalog.yaml
```

This includes rule metadata (id/title/sources) plus each rule’s `config_model` JSON schema.

To emit JSON instead:

```bash
python -m common.rules_engine.catalog --format json > rules_catalog.json
```
