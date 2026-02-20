from decimal import Decimal

from common.rules_engine.models import AccountBalance, EvidenceBundle, EvidenceItem, RuleStatus
from common.rules_engine.rules.bs_fixed_asset_register_reconciles import (
    BS_FIXED_ASSET_REGISTER_RECONCILES,
)


def _balance_sheet_accounts():
    return [
        AccountBalance(
            account_ref="1501",
            name="Computer Equipment",
            type="Fixed Asset",
            subtype="FurnitureAndEquipment",
            balance=Decimal("37852.30"),
        ),
        AccountBalance(
            account_ref="report::Total Computer Equipment",
            name="Total Computer Equipment",
            type="Fixed Asset",
            subtype="FurnitureAndEquipment",
            balance=Decimal("12787.36"),
        ),
        AccountBalance(
            account_ref="1700",
            name="Equipment",
            type="Fixed Asset",
            subtype="FurnitureAndEquipment",
            balance=Decimal("2650.41"),
        ),
    ]


def test_fixed_asset_register_reconciles_pass(make_ctx, make_balance_sheet, period_end):
    bs = make_balance_sheet(accounts=_balance_sheet_accounts())
    evidence = EvidenceBundle(
        items=[
            EvidenceItem(
                evidence_type="fixed_asset_register_balance",
                source="fixture",
                as_of_date=period_end,
                meta={
                    "items": [
                        {
                            "asset_class": "1501 Computer Equipment",
                            "account_name_match": "Computer Equipment",
                            "balance": "12787.36",
                        },
                        {
                            "asset_class": "Equipment",
                            "account_name_match": "Equipment",
                            "balance": "2650.41",
                        },
                    ]
                },
            )
        ]
    )
    res = BS_FIXED_ASSET_REGISTER_RECONCILES().evaluate(
        make_ctx(balance_sheet=bs, evidence=evidence, client_rules={})
    )

    assert res.status == RuleStatus.PASS


def test_fixed_asset_register_reconciles_fail_on_mismatch(make_ctx, make_balance_sheet, period_end):
    bs = make_balance_sheet(accounts=_balance_sheet_accounts())
    evidence = EvidenceBundle(
        items=[
            EvidenceItem(
                evidence_type="fixed_asset_register_balance",
                source="fixture",
                as_of_date=period_end,
                meta={
                    "items": [
                        {
                            "asset_class": "Computer Equipment",
                            "account_name_match": "Computer Equipment",
                            "balance": "12000.00",
                        }
                    ]
                },
            )
        ]
    )
    res = BS_FIXED_ASSET_REGISTER_RECONCILES().evaluate(
        make_ctx(balance_sheet=bs, evidence=evidence, client_rules={})
    )
    assert res.status == RuleStatus.FAIL


def test_fixed_asset_register_reconciles_needs_review_when_mapping_missing(
    make_ctx, make_balance_sheet, period_end
):
    bs = make_balance_sheet(accounts=_balance_sheet_accounts())
    evidence = EvidenceBundle(
        items=[
            EvidenceItem(
                evidence_type="fixed_asset_register_balance",
                source="fixture",
                as_of_date=period_end,
                meta={"items": [{"asset_class": "Website", "balance": "12685.80"}]},
            )
        ]
    )
    res = BS_FIXED_ASSET_REGISTER_RECONCILES().evaluate(
        make_ctx(balance_sheet=bs, evidence=evidence, client_rules={})
    )
    assert res.status == RuleStatus.NEEDS_REVIEW


def test_fixed_asset_register_reconciles_needs_review_when_evidence_missing(
    make_ctx, make_balance_sheet
):
    bs = make_balance_sheet(accounts=_balance_sheet_accounts())
    res = BS_FIXED_ASSET_REGISTER_RECONCILES().evaluate(
        make_ctx(balance_sheet=bs, client_rules={})
    )
    assert res.status == RuleStatus.NEEDS_REVIEW


def test_fixed_asset_register_reconciles_not_applicable_without_fixed_assets(
    make_ctx, make_balance_sheet
):
    bs = make_balance_sheet(
        accounts=[
            AccountBalance(
                account_ref="1",
                name="Cash",
                type="Bank",
                subtype="CashOnHand",
                balance=Decimal("100.00"),
            )
        ]
    )
    res = BS_FIXED_ASSET_REGISTER_RECONCILES().evaluate(
        make_ctx(balance_sheet=bs, client_rules={})
    )
    assert res.status == RuleStatus.NOT_APPLICABLE
