from datetime import date

import pytest

from common.rules_engine.models import RuleStatus
from common.rules_engine.rules.bs_uncleared_items_investigated_and_flagged import (
    BS_UNCLEARED_ITEMS_INVESTIGATED_AND_FLAGGED,
)


@pytest.fixture
def period_end() -> date:
    # Match the provided example: Period Ending 31/10/2025.
    return date(2025, 10, 31)


def test_uncleared_items_pass_and_ignores_after_date(
    make_balance_sheet, make_reconciliation_snapshot, make_ctx
):
    rule_cfg = {"BS-UNCLEARED-ITEMS-INVESTIGATED-AND-FLAGGED": {"months_old_threshold": 2}}
    bs = make_balance_sheet(accounts=[{"account_ref": "B1", "name": "Checking", "type": "Bank", "balance": "0"}])
    recs = (
        make_reconciliation_snapshot(
            account_ref="B1",
            account_name="Checking",
            statement_end_date=date(2025, 10, 31),
            meta={
                "uncleared_items": {
                    "as_at": [{"txn_date": "2025-09-15", "description": "Recent outstanding payment", "amount": "10"}],
                    "after_date": [
                        # Old, but should be ignored because it's "after date" (not as-at statement end).
                        {"txn_date": "2025-01-01", "description": "Future-dated section item", "amount": "999"}
                    ],
                }
            },
        ),
    )
    res = BS_UNCLEARED_ITEMS_INVESTIGATED_AND_FLAGGED().evaluate(
        make_ctx(balance_sheet=bs, reconciliations=recs, client_rules=rule_cfg)
    )
    assert res.status == RuleStatus.PASS
    assert res.details[0].values.get("flagged_uncleared_items_count") == 0
    assert res.details[0].values.get("uncleared_items_after_date_ignored_count") == 1


def test_uncleared_items_warn_when_as_at_items_older_than_2_months(
    make_balance_sheet, make_reconciliation_snapshot, make_ctx
):
    rule_cfg = {"BS-UNCLEARED-ITEMS-INVESTIGATED-AND-FLAGGED": {"months_old_threshold": 2}}
    bs = make_balance_sheet(accounts=[{"account_ref": "B1", "name": "Checking", "type": "Bank", "balance": "0"}])
    recs = (
        make_reconciliation_snapshot(
            account_ref="B1",
            account_name="Checking",
            statement_end_date=date(2025, 10, 31),
            meta={
                "uncleared_items": {
                    "as_at": [
                        # Older than 2 months as-of 2025-10-31 (threshold date: 2025-08-31).
                        {"txn_date": "2025-08-01", "description": "Old outstanding deposit", "amount": "100"},
                        # Exactly 2 months old should not be flagged by the strict "< threshold_date" rule.
                        {"txn_date": "2025-08-31", "description": "Borderline item", "amount": "5"},
                    ],
                    "after_date": [],
                }
            },
        ),
    )
    res = BS_UNCLEARED_ITEMS_INVESTIGATED_AND_FLAGGED().evaluate(
        make_ctx(balance_sheet=bs, reconciliations=recs, client_rules=rule_cfg)
    )
    assert res.status == RuleStatus.WARN
    assert res.details[0].values.get("flagged_uncleared_items_count") == 1
    assert "check with the client" in (res.human_action or "").lower()


def test_uncleared_items_needs_review_when_uncleared_list_missing(
    make_balance_sheet, make_reconciliation_snapshot, make_ctx
):
    rule_cfg = {"BS-UNCLEARED-ITEMS-INVESTIGATED-AND-FLAGGED": {}}
    bs = make_balance_sheet(accounts=[{"account_ref": "B1", "name": "Checking", "type": "Bank", "balance": "0"}])
    recs = (make_reconciliation_snapshot(account_ref="B1", account_name="Checking", statement_end_date=date(2025, 10, 31)),)
    res = BS_UNCLEARED_ITEMS_INVESTIGATED_AND_FLAGGED().evaluate(
        make_ctx(balance_sheet=bs, reconciliations=recs, client_rules=rule_cfg)
    )
    assert res.status == RuleStatus.NEEDS_REVIEW


def test_uncleared_items_needs_review_when_any_item_has_unparseable_date(
    make_balance_sheet, make_reconciliation_snapshot, make_ctx
):
    rule_cfg = {"BS-UNCLEARED-ITEMS-INVESTIGATED-AND-FLAGGED": {}}
    bs = make_balance_sheet(accounts=[{"account_ref": "B1", "name": "Checking", "type": "Bank", "balance": "0"}])
    recs = (
        make_reconciliation_snapshot(
            account_ref="B1",
            account_name="Checking",
            statement_end_date=date(2025, 10, 31),
            meta={"uncleared_items": {"as_at": [{"txn_date": "not-a-date"}], "after_date": []}},
        ),
    )
    res = BS_UNCLEARED_ITEMS_INVESTIGATED_AND_FLAGGED().evaluate(
        make_ctx(balance_sheet=bs, reconciliations=recs, client_rules=rule_cfg)
    )
    assert res.status == RuleStatus.NEEDS_REVIEW


def test_uncleared_items_not_applicable_when_disabled(make_balance_sheet, make_ctx):
    rule_cfg = {"BS-UNCLEARED-ITEMS-INVESTIGATED-AND-FLAGGED": {"enabled": False}}
    bs = make_balance_sheet(accounts=[])
    res = BS_UNCLEARED_ITEMS_INVESTIGATED_AND_FLAGGED().evaluate(make_ctx(balance_sheet=bs, client_rules=rule_cfg))
    assert res.status == RuleStatus.NOT_APPLICABLE

