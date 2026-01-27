from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Iterable, Optional

from .context import RuleContext
from .models import RuleRunReport, RuleStatus
from .registry import registry


class RulesRunner:
    def __init__(self, rules: Optional[Iterable] = None):
        self._rules = list(rules) if rules is not None else registry.create_all()

    def run(self, ctx: RuleContext, *, rule_ids: Optional[set[str]] = None) -> RuleRunReport:
        results = []
        for rule in self._rules:
            if rule_ids is not None and rule.rule_id not in rule_ids:
                continue
            results.append(rule.evaluate(ctx))

        totals: dict[RuleStatus, int] = {}
        for res in results:
            totals[res.status] = totals.get(res.status, 0) + 1

        return RuleRunReport(
            run_id=str(uuid.uuid4()),
            generated_at=datetime.now(timezone.utc),
            period_end=ctx.period_end,
            results=results,
            totals=totals,
        )

