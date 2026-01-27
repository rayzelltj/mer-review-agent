from __future__ import annotations

from ..config import PettyCashMatchRuleConfig
from ..context import RuleContext, quantize_amount
from ..models import RuleResult, RuleResultDetail, RuleStatus, Severity
from ..registry import register_rule
from ..rule import Rule


@register_rule
class BS_PETTY_CASH_MATCH(Rule):
    rule_id = "BS-PETTY-CASH-MATCH"
    rule_title = "Petty cash matches between QBO and client's supporting document"
    best_practices_reference = "Petty cash"
    sources = ["QBO", "Google Drive (supporting document)"]
    config_model = PettyCashMatchRuleConfig

    def evaluate(self, ctx: RuleContext) -> RuleResult:
        cfg = ctx.client_config.get_rule_config(self.rule_id, PettyCashMatchRuleConfig)
        if not cfg.enabled:
            return RuleResult(
                rule_id=self.rule_id,
                rule_title=self.rule_title,
                best_practices_reference=self.best_practices_reference,
                sources=self.sources,
                status=RuleStatus.NOT_APPLICABLE,
                severity=Severity.INFO,
                summary="Rule disabled by client configuration.",
            )

        if not cfg.account_ref:
            return RuleResult(
                rule_id=self.rule_id,
                rule_title=self.rule_title,
                best_practices_reference=self.best_practices_reference,
                sources=self.sources,
                status=RuleStatus.NEEDS_REVIEW,
                severity=cfg.default_severity,
                summary=f"Petty cash account not configured for period end {ctx.period_end.isoformat()}.",
                human_action="Configure the petty cash account ref for this client.",
            )

        bs_balance = ctx.get_account_balance(cfg.account_ref)
        if bs_balance is None:
            return RuleResult(
                rule_id=self.rule_id,
                rule_title=self.rule_title,
                best_practices_reference=self.best_practices_reference,
                sources=self.sources,
                status=RuleStatus.NOT_APPLICABLE,
                severity=cfg.not_applicable_severity,
                summary=f"Petty cash account not found in balance sheet snapshot as of {ctx.period_end.isoformat()}.",
                details=[
                    RuleResultDetail(
                        key=cfg.account_ref,
                        message="Account not found in balance sheet snapshot.",
                        values={
                            "account_name": cfg.account_name,
                            "period_end": ctx.period_end.isoformat(),
                            "status": RuleStatus.NOT_APPLICABLE.value,
                        },
                    )
                ],
                human_action="Confirm whether petty cash exists in QBO and map the correct petty cash account.",
            )

        evidence_item = ctx.evidence.first(cfg.evidence_type)
        if evidence_item is None or evidence_item.amount is None:
            return RuleResult(
                rule_id=self.rule_id,
                rule_title=self.rule_title,
                best_practices_reference=self.best_practices_reference,
                sources=self.sources,
                status=RuleStatus.NEEDS_REVIEW,
                severity=cfg.default_severity,
                summary=(
                    f"Missing petty cash supporting document amount for {ctx.period_end.isoformat()}; cannot verify."
                ),
                evidence_used=[evidence_item] if evidence_item else [],
                human_action="Request/attach petty cash supporting document (or extracted amount) for this period end.",
            )

        bs_q = quantize_amount(bs_balance, cfg.amount_quantize)
        support_q = quantize_amount(evidence_item.amount, cfg.amount_quantize)
        diff = abs(bs_q - support_q)

        if diff == 0:
            status = RuleStatus.PASS
            severity = cfg.pass_severity
            summary = f"Petty cash matches exactly as of {ctx.period_end.isoformat()}."
        else:
            status = RuleStatus.FAIL
            severity = cfg.fail_severity
            summary = f"Petty cash does not match support as of {ctx.period_end.isoformat()} (diff {diff})."

        human_action = None
        if status != RuleStatus.PASS:
            human_action = "Verify petty cash support and explain the variance; correct entries or update support."

        return RuleResult(
            rule_id=self.rule_id,
            rule_title=self.rule_title,
            best_practices_reference=self.best_practices_reference,
            sources=self.sources,
            status=status,
            severity=severity,
            summary=summary,
            details=[
                RuleResultDetail(
                    key=cfg.account_ref,
                    message="Petty cash compared to supporting document.",
                    values={
                        "account_name": cfg.account_name,
                        "period_end": ctx.period_end.isoformat(),
                        "bs_balance": str(bs_q),
                        "support_amount": str(support_q),
                        "difference": str(diff),
                        "status": status.value,
                    },
                )
            ],
            evidence_used=[evidence_item],
            human_action=human_action,
        )
